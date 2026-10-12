"use strict";

const { GoogleGenAI } = require("@google/genai");
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
  classifyGeminiError,
  validatePayload,
} = require("./src/gemini");

initializeApp();

const geminiApiKey = defineSecret("GEMINI_API_KEY");
const geminiModel = defineString("GEMINI_MODEL", {
  default: "gemini-3.8-flash",
});
const geminiFallbackModels = defineString("GEMINI_MODEL_FALLBACKS", {
  default: "",
});
const DAILY_REQUEST_LIMIT = 30;

async function consumeDailyRequest(uid) {
  const firestore = getFirestore();
  const userDocumentId = Buffer.from(uid).toString("base64url");
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

async function handleGeminiRequest(req, res) {
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

  let apiKey;
  try {
    apiKey = geminiApiKey.value();
  } catch {
    apiKey = "";
  }
  if (!apiKey) {
    logger.error("Gemini request rejected: category=missing_server_secret");
    res.status(503).json({
      error: {
        code: "GEMINI_CONFIGURATION",
        message: "The AI service is not configured. Please contact the administrator.",
      },
    });
    return;
  }

  let allowed;
  try {
    allowed = await consumeDailyRequest(decodedToken.uid);
  } catch {
    logger.error("Gemini request rejected: category=usage_store_failure");
    res.status(503).json({
      error: {
        code: "USAGE_STORE_UNAVAILABLE",
        message: "The AI service is temporarily unavailable. Please retry.",
      },
    });
    return;
  }
  if (!allowed) {
    logger.warn("Gemini request rejected: category=user_daily_limit status=429");
    res.status(429).json({
      error: {
        code: "GEMINI_DAILY_LIMIT",
        message: "You've reached today's AI request limit.",
      },
    });
    return;
  }

  const primaryModel = geminiModel.value().trim() || "gemini-3.8-flash";
  const fallbackModels = geminiFallbackModels.value()
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  const models = [...new Set([primaryModel, ...fallbackModels])];
  let lastFailure;
  try {
    const client = new GoogleGenAI({ apiKey });
    for (const model of models) {
      try {
        const response = await client.models.generateContent({
          model,
          contents: input.prompt,
          config: {
            systemInstruction: input.systemInstruction,
            maxOutputTokens: input.maxOutputTokens,
            temperature: 0.2,
            ...(input.responseSchema
              ? {
                  responseMimeType: "application/json",
                  responseSchema: input.responseSchema,
                }
              : {}),
          },
        });
        if (typeof response.text === "string" && response.text.trim()) {
          res.status(200).json({ text: response.text });
          return;
        }
        lastFailure = new Error("Gemini returned an empty response.");
      } catch (error) {
        lastFailure = error;
        logger.warn("Gemini model failed; trying the next configured model: model=%s", model);
        const failureCategory = classifyGeminiError(error).category;
        if (
          failureCategory === "network_failure" ||
          failureCategory === "network_timeout"
        ) {
          break;
        }
      }
    }
    const failure = lastFailure
      ? classifyGeminiError(lastFailure)
      : {
          status: 503,
          code: "GEMINI_UNAVAILABLE",
          message: "All configured Gemini models are unavailable.",
        };
    logger.warn(
      "Gemini request failed: category=%s status=%s models=%s",
      failure.category,
      failure.status,
      models.join(","),
    );
    res.status(failure.status).json({
      error: { code: failure.code, message: failure.message },
    });
  } catch (error) {
    const failure = classifyGeminiError(error);
    logger.warn(
      "Gemini request failed: category=%s status=%s models=%s",
      failure.category,
      Number(error?.status ?? error?.code) || "network",
      models.join(","),
    );
    res.status(failure.status).json({
      error: { code: failure.code, message: failure.message },
    });
  }
}

exports.generateGemini = onRequest(
  {
    region: "us-central1",
    cors: true,
    timeoutSeconds: 60,
    maxInstances: 10,
    secrets: [geminiApiKey],
  },
  handleGeminiRequest,
);
