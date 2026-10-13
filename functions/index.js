"use strict";

const { initializeApp } = require("firebase-admin/app");
const { getAuth } = require("firebase-admin/auth");
const {
  FieldValue,
  getFirestore,
} = require("firebase-admin/firestore");
const { defineSecret, defineString } = require("firebase-functions/params");
const { onRequest } = require("firebase-functions/v2/https");
const logger = require("firebase-functions/logger");

const {
  RequestError,
  classifyGroqError,
  groqPayload,
  validatePayload,
} = require("./src/groq");

initializeApp();

const groqApiKey = defineSecret("GROQ_API_KEY");
const groqModel = defineString("GROQ_MODEL", {
  default: "openai/gpt-oss-20b",
});
const DAILY_REQUEST_LIMIT = 30;
const GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions";

async function consumeDailyRequest(uid) {
  const firestore = getFirestore();
  const userDocumentId = Buffer.from(uid).toString("base64url");
  // Keep the legacy collection path so deployment does not reset user limits.
  const usageRef = firestore.collection("_gemini_usage").doc(userDocumentId);
  const day = new Date().toISOString().slice(0, 10);

  return firestore.runTransaction(async (transaction) => {
    const snapshot = await transaction.get(usageRef);
    const data = snapshot.exists ? snapshot.data() : undefined;
    const count = data?.day === day ? Number(data.count) || 0 : 0;
    if (count >= DAILY_REQUEST_LIMIT) {
      return false;
    }
    transaction.set(usageRef, {
      day,
      count: count + 1,
      updatedAt: FieldValue.serverTimestamp(),
    });
    return true;
  });
}

async function handleGroqRequest(req, res) {
  if (req.method !== "POST") {
    res.set("Allow", "POST");
    res.status(405).json({
      error: { code: "METHOD_NOT_ALLOWED", message: "Use POST." },
    });
    return;
  }

  const match = /^Bearer\s+(\S+)$/i.exec(req.get("authorization") || "");
  if (!match) {
    res.status(401).json({
      error: { code: "UNAUTHENTICATED", message: "Sign in to continue." },
    });
    return;
  }

  let decodedToken;
  try {
    decodedToken = await getAuth().verifyIdToken(match[1], true);
  } catch {
    res.status(401).json({
      error: { code: "UNAUTHENTICATED", message: "Sign in again to continue." },
    });
    return;
  }

  let input;
  try {
    input = validatePayload(req.body);
  } catch (error) {
    if (!(error instanceof RequestError)) {
      throw error;
    }
    res.status(error.status).json({
      error: { code: error.code, message: error.message },
    });
    return;
  }

  const apiKey = groqApiKey.value().trim();
  if (!apiKey) {
    logger.error("Groq request rejected: category=missing_server_secret");
    res.status(503).json({
      error: {
        code: "GROQ_NOT_CONFIGURED",
        message: "The AI service is not configured. Contact the administrator.",
      },
    });
    return;
  }

  let allowed;
  try {
    allowed = await consumeDailyRequest(decodedToken.uid);
  } catch {
    logger.error("Groq request rejected: category=usage_store_failure");
    res.status(503).json({
      error: {
        code: "USAGE_STORE_UNAVAILABLE",
        message: "The AI service is temporarily unavailable. Please retry.",
      },
    });
    return;
  }
  if (!allowed) {
    logger.warn("Groq request rejected: category=user_daily_limit status=429");
    res.status(429).json({
      error: {
        code: "GROQ_DAILY_LIMIT",
        message: "You've reached today's AI request limit.",
      },
    });
    return;
  }

  const model = groqModel.value().trim() || "openai/gpt-oss-20b";
  try {
    const response = await fetch(GROQ_API_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(groqPayload(input, model)),
      signal: AbortSignal.timeout(50_000),
    });
    if (!response.ok) {
      let providerError = {};
      try {
        const body = await response.json();
        providerError = body?.error ?? {};
      } catch {
        // The status code is sufficient to classify an unreadable error body.
      }
      const failure = classifyGroqError({
        status: response.status,
        code: providerError?.code,
      });
      logger.warn(
        "Groq request failed: category=%s status=%s model=%s",
        failure.category,
        response.status,
        model,
      );
      res.status(failure.status).json({
        error: { code: failure.code, message: failure.message },
      });
      return;
    }

    let body;
    try {
      body = await response.json();
    } catch {
      res.status(502).json({
        error: {
          code: "GROQ_INVALID_RESPONSE",
          message: "The AI service returned an invalid response. Please retry.",
        },
      });
      return;
    }
    const text = body?.choices?.[0]?.message?.content;
    if (typeof text !== "string" || !text.trim()) {
      res.status(502).json({
        error: {
          code: "GROQ_INVALID_RESPONSE",
          message: "The AI service returned an empty or invalid response. Please retry.",
        },
      });
      return;
    }
    res.status(200).json({ text: text.trim() });
  } catch (error) {
    const failure = classifyGroqError(error);
    logger.warn(
      "Groq request failed: category=%s model=%s",
      failure.category,
      model,
    );
    res.status(failure.status).json({
      error: { code: failure.code, message: failure.message },
    });
  }
}

exports.generateGroq = onRequest(
  {
    region: "us-central1",
    cors: true,
    timeoutSeconds: 60,
    maxInstances: 10,
    secrets: [groqApiKey],
  },
  handleGroqRequest,
);
