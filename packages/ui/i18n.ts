import { serverMessages } from "./server-messages";
import { messages } from "./messages";

export type Language = "en" | "ru";
export type Message = keyof typeof messages;
export const languageStorageKey = "spiking-bug.language";

const isLanguage = (value: unknown): value is Language =>
  value === "en" || value === "ru";

function readLanguage(): Language {
  const url = new URL(location.href);
  const linked = url.searchParams.get("lang");
  if (isLanguage(linked)) {
    try {
      localStorage.setItem(languageStorageKey, linked);
    } catch {
      // The URL still selects the language when browser storage is disabled.
    }
    url.searchParams.delete("lang");
    history.replaceState(history.state, "", url);
    return linked;
  }
  try {
    const stored = localStorage.getItem(languageStorageKey);
    if (isLanguage(stored)) return stored;
  } catch {
    // A new or restricted browser session starts in English.
  }
  return "en";
}

export const language = readLanguage();
export const locale = language === "ru" ? "ru-RU" : "en-US";
document.documentElement.lang = language;

export function t(key: Message, ...values: (string | number)[]): string {
  const template = language === "en" ? messages[key] : key;
  return template.replace(/\{(\d+)\}/g, (match, index: string) =>
    values[Number(index)] === undefined ? match : String(values[Number(index)]),
  );
}

export function changeLanguage(next: string) {
  if (!isLanguage(next) || next === language) return;
  // Reload only this client. The server, simulation and saved project keep running.
  const url = new URL(location.href);
  try {
    localStorage.setItem(languageStorageKey, next);
  } catch {
    url.searchParams.set("lang", next);
  }
  location.replace(url);
}

// Ports have separate localStorage. Carry the choice when navigating between clients.
export function languageLink(url: string): string {
  const target = new URL(url, location.href);
  target.searchParams.set("lang", language);
  return target.href;
}

// Server validation messages may contain field names, IDs, ranges, or driver errors.
// Only their known message templates are translated; dynamic data stays intact.
export function translateServerMessage(message: string): string {
  if (language === "ru") return message;
  if (Object.hasOwn(serverMessages, message)) return serverMessages[message];
  for (const [pattern, translation, nestedDiagnostic] of serverPatterns) {
    const match = pattern.exec(message);
    if (match)
      return translation.replace(/\{(\d+)\}/g, (_, index: string) => {
        const value = match[Number(index) + 1];
        return nestedDiagnostic && index === "1"
          ? translateServerMessage(value)
          : value;
      });
  }
  return message;
}

const serverPatterns = Object.entries(serverMessages)
  .filter(([key]) => /\{\d+\}/.test(key))
  .map(
    ([key, translation]) =>
      [
        new RegExp(
          "^" +
            key
              .split(/\{\d+\}/)
              .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
              .join("([\\s\\S]*?)") +
            "$",
        ),
        translation,
        key === "Устройство {0} недоступно; выбран CPU. {1}" ||
          key === "Не удалось запустить {0}: {1}",
      ] as const,
  );
