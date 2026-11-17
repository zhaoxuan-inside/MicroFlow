import { test } from "node:test";
import assert from "node:assert/strict";
import { entityLabelKey } from "../src/lib/entities.ts";

const MAPPING = { "user.account": "entity_user_account", "forum.thread": "entity_forum_thread" };

test("已登记实体返回 i18n 文案键", () => {
  assert.equal(entityLabelKey("user.account", MAPPING), "entity_user_account");
  assert.equal(entityLabelKey("forum.thread", MAPPING), "entity_forum_thread");
});

test("未登记实体如实回退原名（不做猜测式美化）", () => {
  assert.equal(entityLabelKey("custom.thing", MAPPING), "custom.thing");
  assert.equal(entityLabelKey("", MAPPING), "");
});
