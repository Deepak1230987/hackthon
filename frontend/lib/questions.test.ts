import assert from "node:assert/strict";
import { test } from "node:test";

import { answerLabel, questionText, typedValue } from "./questions.ts";
import type { Question } from "./types.ts";

const question = (over: Partial<Question>): Question => ({
  name: "x",
  type: "str",
  options: null,
  min: null,
  max: null,
  question_en: "An English question?",
  unit: null,
  ...over,
});

test("every registry field has Hindi, and an unknown one falls back to English", () => {
  const names = [
    "age", "gender", "state", "district", "annual_income_inr", "occupation", "social_category",
    "land_holding_hectares", "business_turnover_inr", "employee_count", "is_bpl", "is_student",
    "has_disability",
  ];
  for (const name of names) {
    assert.match(questionText(question({ name })), /[ऀ-ॿ]/, name);
  }
  assert.equal(questionText(question({ name: "new_field" })), "An English question?");
});

test("the confirmation reads naturally", () => {
  assert.equal(answerLabel(question({ type: "bool" }), true), "हाँ");
  assert.equal(answerLabel(question({ type: "bool" }), false), "नहीं");
  assert.equal(answerLabel(question({ type: "enum" }), "farmer"), "किसान");
  assert.equal(
    answerLabel(question({ type: "float", unit: "INR" }), 250000),
    "2,50,000 रुपये",
  );
  assert.equal(answerLabel(question({ type: "int", unit: "years" }), 25), "25 साल");
});

test("typed numbers accept commas, and anything else is left for the backend", () => {
  const income = question({ type: "float" });
  assert.equal(typedValue(income, " 2,50,000 "), 250000);
  assert.equal(typedValue(income, "abc"), "abc");
  assert.equal(typedValue(income, ""), "");
  assert.equal(typedValue(question({ type: "str" }), " Pune "), "Pune");
});
