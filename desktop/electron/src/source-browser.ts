import { isIP } from "node:net";
import { BrowserWindow, ipcMain, session, shell, WebContentsView } from "electron";

export function isSourceUrl(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 8000) return false;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase().replace(/\.$/, "");
    // Source pages use public domain names; IP literals and local services are excluded.
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password
      && host.includes(".") && !host.startsWith("[") && !isIP(host)
      && !/(^|\.)(localhost|local|internal|test|invalid)$/.test(host);
  } catch { return false; }
}

export function sourceBounds(value: unknown, width: number, height: number) {
  const bounds = value as Record<string, unknown> | null;
  if (!bounds || !["x", "y", "width", "height"].every((key) => typeof bounds[key] === "number" && Number.isFinite(bounds[key]))) {
    throw new Error("Invalid source browser bounds");
  }
  const x = Math.max(0, Math.min(width, Math.round(bounds.x as number)));
  const y = Math.max(0, Math.min(height, Math.round(bounds.y as number)));
  return { x, y, width: Math.max(0, Math.min(width - x, Math.round(bounds.width as number))), height: Math.max(0, Math.min(height - y, Math.round(bounds.height as number))) };
}

export function registerSourceBrowser(window: BrowserWindow, assertSender: (sender: Electron.WebContents) => void) {
  let view: WebContentsView | undefined;
  let error: string | undefined;
  const isolated = session.fromPartition("vibe-source-browser");
  isolated.setPermissionCheckHandler(() => false);
  isolated.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  isolated.on("will-download", (event) => {
    event.preventDefault();
    error = "Không thể tải file trong khung nguồn. Chọn mở bằng trình duyệt ngoài để tải.";
    publish();
  });
  // Chromium's bundled PDF viewer needs its own extension and shared UI resources.
  // These origins stay unavailable to user navigation and external-window requests.
  const pdfViewerOrigin = "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/";
  isolated.webRequest.onBeforeRequest((details, callback) => {
    const bundledPdfResource = details.url.startsWith(pdfViewerOrigin)
      || (details.url.startsWith("chrome://resources/") && details.frame?.url.startsWith(pdfViewerOrigin));
    callback({ cancel: !isSourceUrl(details.url) && !bundledPdfResource });
  });
  function publish(closed = false) {
    if (!view || window.isDestroyed()) return;
    const contents = view.webContents;
    window.webContents.send("desktop:source-state", {
      url: contents.getURL(), title: contents.getTitle(), loading: contents.isLoading(),
      canGoBack: contents.navigationHistory.canGoBack(), canGoForward: contents.navigationHistory.canGoForward(), error, closed,
    });
  }
  function close() {
    if (!view) return;
    window.contentView.removeChildView(view);
    view.webContents.close();
    view = undefined;
  }
  function resize(bounds: unknown) {
    const [width, height] = window.getContentSize();
    const zoom = window.webContents.getZoomFactor();
    const rect = sourceBounds(bounds, width / zoom, height / zoom);
    view?.setBounds({ x: Math.round(rect.x * zoom), y: Math.round(rect.y * zoom), width: Math.round(rect.width * zoom), height: Math.round(rect.height * zoom) });
  }
  function navigate(url: string) {
    const current = view;
    if (!current || !isSourceUrl(url)) return;
    error = undefined;
    void current.webContents.loadURL(url).catch(() => {
      if (view !== current) return;
      error = "Không thể tải trang nguồn. Hãy thử lại hoặc mở bằng trình duyệt ngoài.";
      publish();
    });
  }
  ipcMain.handle("desktop:source-open", (event, url: unknown, bounds: unknown) => {
    assertSender(event.sender);
    if (event.senderFrame !== window.webContents.mainFrame || !isSourceUrl(url)) throw new Error("Source URL rejected");
    const [width, height] = window.getContentSize();
    sourceBounds(bounds, width, height);
    close();
    view = new WebContentsView({ webPreferences: {
      session: isolated, contextIsolation: true, sandbox: true, nodeIntegration: false,
      webSecurity: true, navigateOnDragDrop: false, plugins: true,
    } });
    const current = view;
    const contents = current.webContents;
    window.contentView.addChildView(current);
    resize(bounds);
    const changed = () => { if (view === current) publish(); };
    contents.on("did-start-loading", changed);
    contents.on("did-stop-loading", changed);
    contents.on("did-navigate", changed);
    contents.on("did-navigate-in-page", changed);
    contents.on("page-title-updated", changed);
    contents.on("will-navigate", (event, target) => { if (!isSourceUrl(target)) event.preventDefault(); });
    contents.on("will-redirect", (event, target) => { if (!isSourceUrl(target)) event.preventDefault(); });
    contents.setWindowOpenHandler(({ url: target }) => { navigate(target); return { action: "deny" }; });
    contents.on("did-fail-load", (_event, code, _description, _url, mainFrame) => {
      if (view !== current || !mainFrame || code === -3) return;
      error = "Không thể tải trang nguồn. Hãy thử lại hoặc mở bằng trình duyệt ngoài.";
      publish();
    });
    contents.on("before-input-event", (event, input) => {
      if (input.key !== "Escape" || input.type !== "keyDown") return;
      event.preventDefault(); publish(true); close(); window.webContents.focus();
    });
    navigate(url);
  });
  ipcMain.on("desktop:source-bounds", (event, bounds: unknown) => { assertSender(event.sender); resize(bounds); });
  ipcMain.on("desktop:source-close", (event) => { assertSender(event.sender); close(); });
  ipcMain.on("desktop:source-navigate", (event, action: unknown) => {
    assertSender(event.sender);
    if (!view) return;
    const contents = view.webContents;
    error = undefined;
    if (action === "back" && contents.navigationHistory.canGoBack()) contents.navigationHistory.goBack();
    else if (action === "forward" && contents.navigationHistory.canGoForward()) contents.navigationHistory.goForward();
    else if (action === "reload") contents.reload();
  });
  ipcMain.on("desktop:source-external", (event, url: unknown) => {
    assertSender(event.sender);
    if (isSourceUrl(url)) void shell.openExternal(url);
  });
  window.webContents.on("did-start-navigation", (_event, _url, _inPlace, mainFrame) => { if (mainFrame) close(); });
  window.on("closed", close);
}
