"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  RequestError,
  classifyGroqError,
  groqPayload,
  toGroqJsonSchema,
  validatePayload,
} = require("../src/groq");

const responseSchema = {
  type: "OBJECT",
  properties: {
    summary: { type: "STRING" },
    recommendations: {
      type: "ARRAY",
      items: {
        type: "OBJECT",
        properties: {
          task_id: { type: "STRING" },
          reason: { type: "STRING" },
        },
        required: ["task_id", "reason"],
      },
    },
  },
  required: ["summary", "recommendations"],
};

test("validates and normalizes an AI request", () => {
  const request = validatePayload({
    prompt: "Help plan my week.",
    system_instruction: "Use only the supplied task data.",
    response_schema: responseSchema,
    max_output_tokens: 700,
  });

  assert.deepEqual(request, {
    prompt: "Help plan my week.",
    systemInstruction: "Use only the supplied task data.",
    responseSchema,
    maxOutputTokens: 700,
  });
});

test("rejects invalid and oversized AI requests", () => {
  assert.throws(
    () => validatePayload({ prompt: "missing other fields" }),
    RequestError,
  );
  assert.throws(
    () =>
      validatePayload({
        prompt: "x".repeat(40_001),
        system_instruction: "instructions",
        max_output_tokens: 700,
      }),
    RequestError,
  );
  assert.throws(
    () =>
      validatePayload({
        prompt: "question",
        system_instruction: "instructions",
        max_output_tokens: 4_001,
      }),
    RequestError,
  );
});

test("builds the Groq chat completions request and strict JSON schema", () => {
  const input = validatePayload({
    prompt: "Prioritize these tasks.",
    system_instruction: "Return the requested structure.",
    response_schema: responseSchema,
    max_output_tokens: 700,
  });
  const request = groqPayload(input, "openai/gpt-oss-20b");

  assert.equal(request.model, "openai/gpt-oss-20b");
  assert.deepEqual(request.messages, [
    { role: "system", content: "Return the requested structure." },
    { role: "user", content: "Prioritize these tasks." },
  ]);
  assert.equal(request.max_completion_tokens, 700);
  assert.equal(request.response_format.type, "json_schema");
  assert.equal(request.response_format.json_schema.strict, true);
  assert.equal(
    request.response_format.json_schema.schema.properties.recommendations
      .items.additionalProperties,
    false,
  );
  assert.deepEqual(toGroqJsonSchema({ type: "STRING" }), { type: "string" });
});

test("maps Groq and network errors to sanitized response categories", () => {
  assert.equal(classifyGroqError({ status: 429 }).code, "GROQ_RATE_LIMIT");
  assert.equal(classifyGroqError({ status: 403 }).code, "GROQ_AUTH");
  assert.equal(classifyGroqError({ status: 404 }).code, "GROQ_MODEL");
  assert.equal(
    classifyGroqError({ status: 503 }).category,
    "upstream_server",
  );
  assert.equal(
    classifyGroqError({ name: "TimeoutError" }).category,
    "network_timeout",
  );
  assert.equal(
    classifyGroqError({ name: "TypeError" }).category,
    "network_failure",
  );
});
