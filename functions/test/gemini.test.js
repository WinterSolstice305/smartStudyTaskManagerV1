"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  RequestError,
  classifyGeminiError,
  validatePayload,
} = require("../src/gemini");

test("validates and normalizes a generation request", () => {
  const request = validatePayload({
    prompt: "Help plan my week.",
    system_instruction: "Use only the supplied task data.",
    response_schema: { type: "OBJECT" },
    max_output_tokens: 700,
  });

  assert.deepEqual(request, {
    prompt: "Help plan my week.",
    systemInstruction: "Use only the supplied task data.",
    responseSchema: { type: "OBJECT" },
    maxOutputTokens: 700,
  });
});

test("rejects invalid and oversized generation requests", () => {
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
        max_output_tokens: 1_501,
      }),
    RequestError,
  );
});

test("maps Gemini errors to sanitized response categories", () => {
  assert.equal(classifyGeminiError({ status: 429 }).code, "GEMINI_RATE_LIMIT");
  assert.equal(classifyGeminiError({ status: 403 }).code, "GEMINI_AUTH");
  assert.equal(classifyGeminiError({ status: 404 }).code, "GEMINI_MODEL");
  assert.equal(
    classifyGeminiError({ status: 503 }).category,
    "upstream_server",
  );
  assert.equal(
    classifyGeminiError({ name: "TimeoutError" }).category,
    "network_timeout",
  );
  assert.equal(
    classifyGeminiError({ status: 504 }).category,
    "network_timeout",
  );
});
