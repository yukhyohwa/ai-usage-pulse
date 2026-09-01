const endpoint = "http://127.0.0.1:8765/chatgpt-usage";

chrome.runtime.onMessage.addListener((message, _sender, respond) => {
  if (message?.type !== "usage") return false;
  fetch(endpoint, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(message.payload)
  })
    .then(response => respond({ok: response.ok}))
    .catch(() => respond({ok: false}));
  return true;
});
