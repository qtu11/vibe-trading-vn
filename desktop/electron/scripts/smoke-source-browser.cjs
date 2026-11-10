const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { app, BrowserWindow } = require("electron");
const { isSourceUrl, sourceBounds, registerSourceBrowser } = require("../dist/source-browser.js");

const profile = fs.mkdtempSync(path.join(os.tmpdir(), "vibe-source-browser-smoke-"));
app.setPath("userData", profile);
app.setPath("sessionData", profile);
app.commandLine.appendSwitch("host-resolver-rules", "MAP source.example 127.0.0.1");
app.commandLine.appendSwitch("no-proxy-server");
const timeout = setTimeout(() => { console.error("Source browser smoke timed out"); app.exit(1); }, 30000);
void app.whenReady().then(async () => {
  for (const url of ["javascript:alert(1)", "file:///private", "http://localhost:8000", "http://127.0.0.1", "http://[::1]", "http://2130706433", "https://user:password@example.com", "http://service.local", "ws://example.com/feed", "wss://example.com/feed", "ftp://example.com/report", "chrome://resources/", "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html"]) assert.equal(isSourceUrl(url), false, url);
  assert.equal(isSourceUrl("https://example.com/report.pdf"), true);
  assert.deepEqual(sourceBounds({ x: -10, y: 20, width: 900, height: 900 }, 800, 600), { x: 0, y: 20, width: 800, height: 580 });
  assert.throws(() => sourceBounds({ x: NaN }, 800, 600));

  const requests = [];
  let pdfBytes;
  const server = http.createServer((request, response) => {
    requests.push({ url: request.url, authorization: request.headers.authorization, cookie: request.headers.cookie });
    if (request.url === "/report.pdf") {
      response.setHeader("Content-Type", "application/pdf");
      response.setHeader("Content-Disposition", "inline; filename=source-report.pdf");
      response.end(pdfBytes);
      return;
    }
    response.setHeader("X-Frame-Options", "DENY");
    response.setHeader("Content-Security-Policy", "frame-ancestors 'none'");
    response.setHeader("Content-Type", "text/html; charset=utf-8");
    response.end(`<title>${request.url === "/next" ? "Next source" : "Source page"}</title><h1>Embedded source</h1><a href="/next" target="_blank" id="next">Next</a>`);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://source.example:${server.address().port}/source`;
  const window = new BrowserWindow({ show: false, webPreferences: { preload: path.join(__dirname, "../dist/preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  registerSourceBrowser(window, (sender) => { assert.equal(sender, window.webContents); });
  await window.webContents.session.cookies.set({ url, name: "private-chat-cookie", value: "fixture-only" });
  window.webContents.session.webRequest.onBeforeSendHeaders((details, callback) => { details.requestHeaders.Authorization = "Bearer fixture-only"; callback({ requestHeaders: details.requestHeaders }); });
  await window.loadURL("data:text/html,<title>Chat harness</title><h1>Chat stays here</h1>");
  pdfBytes = await window.webContents.printToPDF({});
  await window.webContents.executeJavaScript(`window.vibeDesktop.sourceBrowser.open(${JSON.stringify(url)}, { x: 500, y: 100, width: 300, height: 400 })`);
  const view = window.contentView.children.find((child) => child.webContents && child.webContents !== window.webContents);
  assert.ok(view, "source view must be attached beside the renderer");
  const sourceContents = view.webContents;
  const waitForPage = async (title) => {
    const until = Date.now() + 10000;
    while (view.webContents.getTitle() !== title || view.webContents.isLoading()) {
      assert.ok(Date.now() < until, `page did not load: ${title}`);
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  };
  await waitForPage("Source page");
  assert.deepEqual(await view.webContents.executeJavaScript("[typeof window.vibeDesktop, typeof require]"), ["undefined", "undefined"]);
  assert.equal(requests[0].authorization, undefined);
  assert.equal(requests[0].cookie, undefined);
  const blockedUrl = `http://127.0.0.1:${server.address().port}/blocked-local-request`;
  assert.equal(await view.webContents.executeJavaScript(`fetch(${JSON.stringify(blockedUrl)}).then(() => false, () => true)`), true);
  assert.equal(requests.some((request) => request.url === "/blocked-local-request"), false);
  await view.webContents.executeJavaScript("document.getElementById('next').click()");
  await waitForPage("Next source");
  assert.equal(view.webContents.navigationHistory.canGoBack(), true);
  await window.webContents.executeJavaScript("window.vibeDesktop.sourceBrowser.navigate('back')");
  await waitForPage("Source page");
  assert.equal(await window.webContents.executeJavaScript("document.title"), "Chat harness");
  await window.webContents.executeJavaScript("window.vibeDesktop.sourceBrowser.close()");
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.ok(sourceContents.isDestroyed());
  await window.webContents.executeJavaScript(`window.sourceStates = []; window.vibeDesktop.sourceBrowser.onState((state) => window.sourceStates.push(state)); window.vibeDesktop.sourceBrowser.open(${JSON.stringify(new URL('/report.pdf', url).href)}, { x: 500, y: 100, width: 300, height: 400 })`);
  const pdfView = window.contentView.children.find((child) => child.webContents && child.webContents !== window.webContents);
  const pdfDeadline = Date.now() + 10000;
  let pdfReady = false;
  let pdfState;
  while (Date.now() < pdfDeadline) {
    const pdfFrame = pdfView.webContents.mainFrame.framesInSubtree.find((frame) => frame.url.startsWith("chrome-extension://"));
    if (pdfFrame) {
      try {
        pdfState = await pdfFrame.executeJavaScript("(() => { const viewer = document.querySelector('pdf-viewer'); const toolbar = viewer?.shadowRoot?.querySelector('viewer-toolbar'); return { viewer: Boolean(viewer), toolbar: Boolean(toolbar), pages: toolbar?.docLength, progress: toolbar?.loadProgress, ownPages: viewer?.docLength_, ownProgress: viewer?.loadProgress_ }; })()");
        pdfReady = pdfState.pages === 1 && pdfState.progress === 100;
      } catch {}
    }
    if (pdfReady) break;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.ok(pdfReady, `PDF viewer did not load: ${JSON.stringify({ pdfState, states: await window.webContents.executeJavaScript('window.sourceStates') })}`);
  assert.equal(pdfView.webContents.getLastWebPreferences().nodeIntegration, false);
  assert.equal(pdfView.webContents.getLastWebPreferences().sandbox, true);
  const pdfRequest = requests.find((request) => request.url === "/report.pdf");
  assert.equal(pdfRequest.authorization, undefined);
  assert.equal(pdfRequest.cookie, undefined);
  await window.webContents.executeJavaScript("window.vibeDesktop.sourceBrowser.close()");
  window.destroy();
  server.close();
  clearTimeout(timeout);
  console.log("Source browser smoke passed: frame-blocked page, navigation, PDF parsed 1 page at 100%, blocked local request, isolated cookies/auth, no bridge, close cleanup");
  app.exit(0);
}).catch((error) => { console.error(error); clearTimeout(timeout); app.exit(1); });
