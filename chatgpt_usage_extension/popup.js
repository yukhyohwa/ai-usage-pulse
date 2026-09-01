chrome.storage.local.get(["lastPayload", "lastStatus"], ({lastPayload, lastStatus}) => {
  document.querySelector("#status").textContent =
    lastStatus || "Open the Codex Analytics Usage page to sync plan limits.";
  if (!lastPayload) return;
  document.querySelector("#data").textContent = [
    lastPayload.five_hour,
    lastPayload.weekly,
    lastPayload.reset_cards
  ].filter(Boolean).join("\n");
});
