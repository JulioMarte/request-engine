export function requestChatwootContext() {
  window.parent?.postMessage({ event: "request_context", type: "request_context" }, "*")
}

export function isProbablyEmbedded() {
  return window.parent !== window
}
