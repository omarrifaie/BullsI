"""What the worker injects into each tab: highlights, the "Needs you" checklist panel, and the sign-in banner."""
import json
from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

HERE: Path = Path(__file__).resolve().parent
SPEC: dict[str, Any] = json.loads((HERE / "workday_fields.json").read_text(encoding="utf-8"))
HIGHLIGHT: str = "#ff00aa"

# Marks every blank the worker left (data-bullpen-blank) and every empty required field that is visible, outside the
# voluntary section, not a password. Returns [{id, label}] for the checklist.
COLLECT_JS: str = """([section, pattern, color]) => {
  if (!document.getElementById('bullpen-style')) {
    const style = document.createElement('style');
    style.id = 'bullpen-style';
    style.textContent = `.bullpen-needs { outline: 3px solid ${color} !important; outline-offset: 2px !important; }`;
    document.head.appendChild(style);
  }
  const voluntary = new RegExp(pattern, 'i');
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const labelOf = el => (el.getAttribute('data-bullpen-blank')
    || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.innerText)
    || el.getAttribute('aria-label')
    || el.closest('label')?.innerText
    || el.closest('.formField, [data-automation-id^="formField"]')?.querySelector('label')?.innerText
    || el.getAttribute('placeholder') || el.name || 'Field').replace(/\\s*\\*\\s*$/, '').trim();
  const isEmpty = el => {
    if (el.matches('input[type=file]')) return el.files.length === 0;
    if (el.matches('input[type=checkbox], input[type=radio]')) return false;
    if (el.matches('input, textarea, select')) return !el.value.trim();
    return /^(select one)?$/i.test(el.innerText.trim());
  };
  const offLimits = el => el.matches('input[type=password]') || !!el.closest(`[data-automation-id="${section}"]`)
    || !!el.closest('#bullpen-panel, #bullpen-signin-banner') || voluntary.test(labelOf(el));
  const marked = [...document.querySelectorAll('[data-bullpen-blank]')];
  const required = [...document.querySelectorAll('[aria-required="true"], [required]')].filter(isEmpty);
  const items = [];
  for (const el of new Set([...marked, ...required])) {
    if (!visible(el) || offLimits(el)) continue;
    if (!el.hasAttribute('data-bullpen-id')) el.setAttribute('data-bullpen-id', String(items.length + 1) + '-' + Date.now());
    el.classList.add('bullpen-needs');
    items.push({id: el.getAttribute('data-bullpen-id'), label: labelOf(el)});
  }
  return items;
}"""

YOUR_CHOICE_JS: str = """([section, pattern]) => {
  const voluntary = new RegExp(pattern, 'i');
  const texts = [];
  document.querySelectorAll('label, legend').forEach(el => {
    if (el.closest('#bullpen-panel, #bullpen-signin-banner')) return;
    const inSection = !!el.closest(`[data-automation-id="${section}"]`);
    if (inSection && el.matches('legend')) return;  // the section heading, not a question
    const text = el.innerText.replace(/\\s+/g, ' ').trim();
    if (text && (inSection || voluntary.test(text)) && !texts.includes(text)) texts.push(text.slice(0, 90));
  });
  return texts;
}"""

PANEL_JS: str = """({title, company, filled, needs, laterNeeds, yourChoice, color}) => {
  document.getElementById('bullpen-panel')?.remove();
  const el = (tag, text, style) => {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (style) node.style.cssText = style;
    return node;
  };
  const panel = el('div', '', `position:fixed;top:80px;right:16px;width:290px;max-height:40vh;overflow:auto;
    z-index:2147483647;background:#fff;color:#1d1d1d;border:2px solid ${color};border-radius:8px;
    box-shadow:0 4px 16px rgba(0,0,0,.2);font:13px/1.4 system-ui,sans-serif;padding:10px 12px;`);
  panel.id = 'bullpen-panel';
  const head = el('div', '', 'display:flex;justify-content:space-between;gap:8px;align-items:flex-start;');
  head.append(el('strong', `BullsI: ${title} at ${company}`));
  const toggle = el('button', 'Hide', 'font:inherit;border:1px solid #ccc;background:#f6f6f6;border-radius:4px;cursor:pointer;');
  toggle.id = 'bullpen-toggle';
  toggle.type = 'button';
  head.append(toggle);
  const body = el('div');
  toggle.onclick = () => { const hidden = body.style.display === 'none'; body.style.display = hidden ? '' : 'none'; toggle.textContent = hidden ? 'Hide' : 'Show'; };
  body.append(el('div', `Filled ${filled} field${filled === 1 ? '' : 's'}`, 'margin:6px 0;'));
  const list = (heading, items, makeItem) => {
    if (!items.length) return;
    body.append(el('div', heading, 'font-weight:600;margin-top:8px;'));
    const ul = el('ul', '', 'margin:4px 0;padding-left:18px;');
    items.forEach(item => ul.append(makeItem(item)));
    body.append(ul);
  };
  list(`Needs you (${needs.length + laterNeeds.length})`, needs, item => {
    const li = el('li');
    const link = el('a', item.label, `color:${color};cursor:pointer;text-decoration:underline;`);
    link.href = '#';
    link.className = 'bullpen-needs-item';
    link.onclick = event => {
      event.preventDefault();
      const target = document.querySelector(`[data-bullpen-id="${item.id}"]`);
      if (target) { target.scrollIntoView({block: 'center'}); target.focus?.(); }
    };
    li.append(link);
    return li;
  });
  list(needs.length ? 'Also left for you' : `Needs you (${laterNeeds.length})`, laterNeeds, text => el('li', text));
  list('Your choice (left blank on purpose)', yourChoice, text => el('li', text, 'color:#555;'));
  body.append(el('div', 'Check every page, then submit it yourself.', 'margin-top:8px;color:#555;'));
  panel.append(head, body);
  document.body.append(panel);
}"""

BANNER_JS: str = """(color) => {
  if (document.getElementById('bullpen-signin-banner')) return;
  const bar = document.createElement('div');
  bar.id = 'bullpen-signin-banner';
  bar.style.cssText = `position:fixed;top:0;left:0;right:0;z-index:2147483647;background:${color};color:#fff;
    font:15px/1.4 system-ui,sans-serif;padding:10px 16px;display:flex;gap:12px;align-items:center;justify-content:center;`;
  const text = document.createElement('span');
  text.textContent = 'BullsI: Sign in or create your account, then click Continue in this banner';
  const button = document.createElement('button');
  button.id = 'bullpen-continue';
  button.type = 'button';
  button.textContent = 'Continue';
  button.style.cssText = 'font:inherit;font-weight:600;padding:4px 14px;border:0;border-radius:4px;cursor:pointer;';
  button.onclick = () => { bar.remove(); window.bullpenContinue(); };
  bar.append(text, button);
  document.body.append(bar);
}"""


async def collect_needs(page: Page) -> list[dict[str, str]]:
  return await page.evaluate(COLLECT_JS, [SPEC["voluntary"]["section"], SPEC["voluntary"]["label_pattern"], HIGHLIGHT])


async def inject_panel(page: Page, job: dict[str, Any], result: dict[str, Any]) -> list[str]:
  """Highlight what's left, add the corner checklist, and return the "needs you" labels for status.json."""
  needs: list[dict[str, str]] = await collect_needs(page)
  later: list[str] = [f"My Information: {label}" for label in result.get("earlier_page_needs", [])]
  later += result.get("needs_you", [])
  your_choice: list[str] = await page.evaluate(
    YOUR_CHOICE_JS, [SPEC["voluntary"]["section"], SPEC["voluntary"]["label_pattern"]])
  await page.evaluate(PANEL_JS, {
    "title": job.get("title") or "Job", "company": job.get("company") or "", "filled": result["filled"],
    "needs": needs, "laterNeeds": later, "yourChoice": your_choice, "color": HIGHLIGHT})
  result["your_choice"] = your_choice
  return [n["label"] for n in needs] + later


async def show_signin_banner(page: Page) -> None:
  """Idempotent; tolerates the page navigating underneath it (the caller re-shows it every second)."""
  try:
    await page.evaluate(BANNER_JS, HIGHLIGHT)
  except PlaywrightError:
    pass
