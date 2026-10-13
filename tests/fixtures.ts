import { test as base, expect } from "@playwright/test";

// Existing interaction tests exercise Russian explicitly; i18n.spec.ts tests English defaults.
export const russianStorageState = {
  cookies: [],
  origins: [5183, 5184].map((port) => ({
    origin: `http://127.0.0.1:${port}`,
    localStorage: [{ name: "spiking-bug.language", value: "ru" }],
  })),
};
export const test = base.extend({ storageState: russianStorageState });
export { expect };
