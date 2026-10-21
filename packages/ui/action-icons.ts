import { escape } from "./api";

const drawings = {
  new: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M12 12v6M9 15h6"/>',
  layout:
    '<rect x="2" y="3" width="5" height="5" rx="1"/><rect x="17" y="3" width="5" height="5" rx="1"/><rect x="9.5" y="16" width="5" height="5" rx="1"/><path d="m7 7 5 9 5-9M7 5.5h10"/>',
  evolution:
    '<path d="M7 2c0 10 10 10 10 20M17 2C17 12 7 12 7 22M8 5h8M10 9h4M10 15h4M8 19h8"/>',
  trials:
    '<path d="M9 3h6M10 3v6l-6 9a2 2 0 0 0 1.7 3h12.6a2 2 0 0 0 1.7-3l-6-9V3M7 15h10"/><path d="M10 18h.01M14 17h.01"/>',
  import:
    '<path d="M12 3v12m-5-5 5 5 5-5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/>',
  export:
    '<path d="M12 15V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/>',
  save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2ZM7 3v6h10V3M7 21v-8h10v8"/>',
  chart: '<path d="M4 3v17h17M8 14l4-5 4 3 5-6"/>',
  chartOff: '<path d="M4 8v12h12M9 13l3-4 4 3 5-6M3 3l18 18"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 17h.01"/>',
  loading: '<path d="M21 12a9 9 0 1 1-9-9"/>',
};
type Icon = keyof typeof drawings;

function icon(name: Icon) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${drawings[name]}</svg>`;
}

export function actionButton(
  id: string,
  name: Icon,
  label: string,
  hint = label,
  attributes = "",
) {
  return `<button id="${id}" type="button" class="icon-action" aria-label="${escape(label)}" data-tooltip="${escape(hint)}" ${attributes}>${icon(name)}</button>`;
}

export function updateAction(
  button: HTMLElement,
  name: Icon,
  label: string,
  hint = label,
) {
  button.innerHTML = icon(name);
  button.setAttribute("aria-label", label);
  button.dataset.tooltip = hint;
}

export function installActionTooltips(root: HTMLElement) {
  const popup = document.createElement("div");
  popup.id = "action-tooltip";
  popup.className = "action-tooltip";
  popup.setAttribute("role", "tooltip");
  popup.hidden = true;
  document.body.append(popup);
  let current: HTMLElement | undefined;
  const hide = () => {
    current?.removeAttribute("aria-describedby");
    current = undefined;
    popup.hidden = true;
  };
  const show = (target: EventTarget | null) => {
    const button =
      target instanceof Element
        ? target.closest<HTMLElement>("[data-tooltip]")
        : null;
    if (!button || !root.contains(button)) return;
    hide();
    current = button;
    const label = button.getAttribute("aria-label")!;
    const hint = button.dataset.tooltip!;
    popup.textContent = label === hint ? label : `${label}. ${hint}`;
    popup.hidden = false;
    button.setAttribute("aria-describedby", popup.id);
    const rect = button.getBoundingClientRect();
    const bounds = popup.getBoundingClientRect();
    popup.style.left = `${Math.max(8, Math.min(window.innerWidth - bounds.width - 8, rect.left + (rect.width - bounds.width) / 2))}px`;
    popup.style.top = `${rect.bottom + bounds.height + 16 < window.innerHeight ? rect.bottom + 8 : Math.max(8, rect.top - bounds.height - 8)}px`;
  };
  root.addEventListener("pointerover", (event) => show(event.target));
  root.addEventListener("focusin", (event) => show(event.target));
  root.addEventListener("pointerout", (event) => {
    if (current && !current.contains(event.relatedTarget as Node | null))
      hide();
  });
  root.addEventListener("focusout", hide);
  root.addEventListener("click", hide);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hide();
  });
  window.addEventListener("resize", hide);
  document.addEventListener("scroll", hide, true);
}
