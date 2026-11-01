import assert from "node:assert/strict";
import { test } from "node:test";

import { moreMayCome, nextPlayable } from "./audioQueue.ts";
import type { Sentence } from "./types.ts";

const sentence = (
  ordinal: number,
  guard_status: Sentence["guard_status"],
  audio_path: string | null,
): Sentence => ({
  id: `s${ordinal}`,
  ordinal,
  language: "hi",
  source_text: "English",
  translated_text: "हिन्दी",
  claim_ids: [],
  audio_path,
  guard_status,
});

test("playback skips a flagged sentence", () => {
  const list = [
    sentence(0, "passed", "audio/a.mp3"),
    sentence(1, "flagged", null),
    sentence(2, "passed", "audio/c.mp3"),
  ];
  assert.equal(nextPlayable(list, 0)?.ordinal, 2);
  assert.equal(nextPlayable(list, 2), undefined);
});

test("playback starts from the first sentence with audio", () => {
  const list = [sentence(0, "flagged", null), sentence(1, "passed", "audio/b.mp3")];
  assert.equal(nextPlayable(list, -1)?.ordinal, 1);
});

test("the player waits only for audio that can still arrive", () => {
  const list = [sentence(0, "passed", "audio/a.mp3"), sentence(1, "passed", null)];
  assert.equal(moreMayCome(list, 0, false), true);
  assert.equal(moreMayCome(list, 0, true), false);
  assert.equal(moreMayCome([sentence(0, "passed", "a"), sentence(1, "flagged", null)], 0, false), false);
});
