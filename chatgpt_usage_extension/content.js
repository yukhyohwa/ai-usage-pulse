// Reads only usage text rendered by ChatGPT and sends it to 127.0.0.1.
// It never reads cookies, local storage, passwords, prompts, or conversations.

function clean(value) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, 240);
}

function pageLines() {
  return (document.body?.innerText || "")
    .split(/\n+/)
    .map(clean)
    .filter(Boolean);
}

function blockBetween(lines, startPattern, endPattern, maxLines = 12) {
  const start = lines.findIndex(line => startPattern.test(line));
  if (start < 0) return [];
  const block = [];
  for (let index = start; index < Math.min(lines.length, start + maxLines); index += 1) {
    if (index > start && endPattern.test(lines[index])) break;
    block.push(lines[index]);
  }
  return block;
}

function compactLimit(block) {
  if (!block.length) return "";
  const joined = block.join(" ");
  const percentage = joined.match(/(?:^|\s)((?:100|\d{1,2})%)(?=\s|$)/)?.[1] || "--";
  const resetStart = block.findIndex(line => /\bresets?\b/i.test(line));
  if (resetStart < 0) return percentage;

  const resetParts = [block[resetStart]];
  for (const line of block.slice(resetStart + 1, resetStart + 3)) {
    if (/^(?:[A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4}|\d{1,2}:\d{2}(?:\s*[AP]M)?)/i.test(line)) {
      resetParts.push(line);
    }
  }
  return `${percentage}, ${clean(resetParts.join(" "))}`;
}

function collectUsage() {
  const lines = pageLines();
  const fiveHour = blockBetween(
    lines,
    /^(?:5[- ]?hour|5 hour usage|primary limit)/i,
    /^(?:weekly|week usage|secondary limit|usage limit resets|reset credits?)/i
  );
  const weekly = blockBetween(
    lines,
    /^(?:weekly|week usage|secondary limit)/i,
    /^(?:usage limit resets|reset credits?|usage breakdown|personal usage)/i
  );

  const fullReset = lines.find(line => /\bfull reset\b/i.test(line)) || "";
  const expires = lines.find(line => /^expires?\b/i.test(line)) || "";
  const fiveHourValue = compactLimit(fiveHour);
  const weeklyValue = compactLimit(weekly);
  const resetCards = [fullReset, expires].filter(Boolean).join(" · ");
  if (!fiveHourValue && !weeklyValue && !resetCards) return null;

  return {
    five_hour: fiveHourValue,
    weekly: weeklyValue,
    reset_cards: resetCards,
    captured_at: new Date().toISOString(),
    source_url: location.href
  };
}

let previousFingerprint = "";

async function syncUsage() {
  const payload = collectUsage();
  if (!payload) return;
  const fingerprint = JSON.stringify({
    five_hour: payload.five_hour,
    weekly: payload.weekly,
    reset_cards: payload.reset_cards,
    source_url: payload.source_url
  });
  if (fingerprint === previousFingerprint) return;

  try {
    const result = await chrome.runtime.sendMessage({type: "usage", payload});
    if (result?.ok) {
      previousFingerprint = fingerprint;
      chrome.storage.local.set({
        lastPayload: payload,
        lastStatus: "Synced to UsagePulse"
      });
    } else {
      chrome.storage.local.set({lastStatus: "UsagePulse is not running"});
    }
  } catch {
    chrome.storage.local.set({lastStatus: "UsagePulse is not running"});
  }
}

let mutationTimer;
new MutationObserver(() => {
  clearTimeout(mutationTimer);
  mutationTimer = setTimeout(syncUsage, 800);
}).observe(document.documentElement, {childList: true, subtree: true, characterData: true});

setInterval(syncUsage, 30_000);
syncUsage();
