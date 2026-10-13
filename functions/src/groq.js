"use strict";

const MAX_PROMPT_LENGTH = 40_000;
const MAX_SYSTEM_INSTRUCTION_LENGTH = 4_000;
const MAX_SCHEMA_LENGTH = 10_000;
const MAX_OUTPUT_TOKENS = 4_000;

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

function toGroqJsonSchema(schema) {
  if (Array.isArray(schema)) {
    return schema.map(toGroqJsonSchema);
  }
  if (!schema || typeof schema !== "object") {
    return schema;
  }
  const converted = Object.fromEntries(
    Object.entries(schema)
      .filter(([key]) => key !== "type")
      .map(([key, value]) => [key, toGroqJsonSchema(value)]),
  );
  if (typeof schema.type === "string") {
    converted.type = schema.type.toLowerCase();
  }
  if (converted.type === "object") {
    converted.additionalProperties = false;
  }
  return converted;
}

function groqPayload(input, model) {
  const payload = {
    model,
    messages: [
      { role: "system", content: input.systemInstruction },
      { role: "user", content: input.prompt },
    ],
    max_completion_tokens: input.maxOutputTokens,
    temperature: 0.2,
  };
  if (input.responseSchema) {
    payload.response_format = {
      type: "json_schema",
      json_schema: {
        name: "task_recommendations",
        strict: true,
        schema: toGroqJsonSchema(input.responseSchema),
      },
    };
  }
  return payload;
}

function classifyGroqError(error) {
  const status = Number(error?.status ?? error?.statusCode ?? error?.code);
  if (status === 429) {
    return {
      status: 429,
      code: "GROQ_RATE_LIMIT",
      category: "quota_or_rate_limit",
      message: "Groq quota or rate limit reached. Wait a moment and retry.",
    };
  }
  if (status === 401 || status === 403) {
    return {
      status: 502,
      code: "GROQ_AUTH",
      category: "authentication_or_access",
      message: "The AI service credentials were rejected.",
    };
  }
  if (status === 404) {
    return {
      status: 502,
      code: "GROQ_MODEL",
      category: "model_not_found",
      message: "The configured Groq model is unavailable.",
    };
  }
  if (status === 400) {
    return {
      status: 400,
      code: "GROQ_INVALID",
      category: "invalid_request",
      message: "Groq could not process this request.",
    };
  }
  if (
    status === 408 ||
    status === 504 ||
    error?.name === "TimeoutError" ||
    error?.name === "AbortError"
  ) {
    return {
      status: 504,
      code: "GROQ_TIMEOUT",
      category: "network_timeout",
      message: "The AI service took too long to respond. Please retry.",
    };
  }
  if (Number.isInteger(status) && status >= 500) {
    return {
      status: 502,
      code: "GROQ_UNAVAILABLE",
      category: "upstream_server",
      message: "Groq is temporarily unavailable. Please try again later.",
    };
  }
  return {
    status: 503,
    code: "GROQ_NETWORK",
    category: "network_failure",
    message: "Could not reach Groq. Check your connection and retry.",
  };
}

module.exports = {
  MAX_OUTPUT_TOKENS,
  RequestError,
  classifyGroqError,
  groqPayload,
  toGroqJsonSchema,
  validatePayload,
};
