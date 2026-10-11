"use strict";

const MAX_PROMPT_LENGTH = 40_000;
const MAX_SYSTEM_INSTRUCTION_LENGTH = 4_000;
const MAX_SCHEMA_LENGTH = 10_000;
const MAX_OUTPUT_TOKENS = 1_500;

class RequestError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function validatePayload(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new RequestError(400, "INVALID_REQUEST", "Invalid AI request.");
  }
  const {
    prompt,
    system_instruction: systemInstruction,
    response_schema: responseSchema,
    max_output_tokens: maxOutputTokens,
  } = body;
  if (
    typeof prompt !== "string" ||
    !prompt.trim() ||
    prompt.length > MAX_PROMPT_LENGTH ||
    typeof systemInstruction !== "string" ||
    !systemInstruction.trim() ||
    systemInstruction.length > MAX_SYSTEM_INSTRUCTION_LENGTH ||
    !Number.isInteger(maxOutputTokens) ||
    maxOutputTokens < 1 ||
    maxOutputTokens > MAX_OUTPUT_TOKENS
  ) {
    throw new RequestError(400, "INVALID_REQUEST", "Invalid AI request.");
  }
  if (responseSchema !== undefined && responseSchema !== null) {
    if (
      typeof responseSchema !== "object" ||
      Array.isArray(responseSchema) ||
      JSON.stringify(responseSchema).length > MAX_SCHEMA_LENGTH
    ) {
      throw new RequestError(400, "INVALID_REQUEST", "Invalid AI request.");
    }
  }
  return {
    prompt,
    systemInstruction,
    responseSchema: responseSchema ?? undefined,
    maxOutputTokens,
  };
}

function classifyGeminiError(error) {
  const status = Number(error?.status ?? error?.code);
  if (status === 429) {
    return {
      status: 429,
      code: "GEMINI_RATE_LIMIT",
      category: "quota_or_rate_limit",
      message: "Gemini quota or rate limit reached. Wait a moment and retry.",
    };
  }
  if (status === 401 || status === 403) {
    return {
      status: 502,
      code: "GEMINI_AUTH",
      category: "authentication_or_access",
      message: "The AI service credentials were rejected.",
    };
  }
  if (status === 404) {
    return {
      status: 502,
      code: "GEMINI_MODEL",
      category: "model_not_found",
      message: "The configured Gemini model is unavailable.",
    };
  }
  if (status === 400) {
    return {
      status: 400,
      code: "GEMINI_INVALID",
      category: "invalid_request",
      message: "Gemini could not process this request.",
    };
  }
  if (status === 408 || status === 504) {
    return {
      status: 504,
      code: "GEMINI_TIMEOUT",
      category: "network_timeout",
      message: "Gemini took too long to respond. Please retry.",
    };
  }
  if (Number.isInteger(status) && status >= 500) {
    return {
      status: 502,
      code: "GEMINI_UNAVAILABLE",
      category: "upstream_server",
      message: "Gemini is temporarily unavailable. Please try again later.",
    };
  }
  if (
    error?.name === "TimeoutError" ||
    error?.name === "AbortError"
  ) {
    return {
      status: 504,
      code: "GEMINI_TIMEOUT",
      category: "network_timeout",
      message: "Gemini took too long to respond. Please retry.",
    };
  }
  return {
    status: 503,
    code: "GEMINI_NETWORK",
    category: "network_failure",
    message: "Could not reach Gemini. Check your connection and retry.",
  };
}

module.exports = {
  MAX_OUTPUT_TOKENS,
  RequestError,
  classifyGeminiError,
  validatePayload,
};
