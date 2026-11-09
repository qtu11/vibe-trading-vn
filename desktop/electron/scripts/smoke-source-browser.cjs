const assert = require("node:assert/strict");
const http = require("node:http");
const path = require("node:path");
const { app, BrowserWindow } = require("electron");
const { isSourceUrl, sourceBounds, registerSourceBrowser } = require("../dist/source-browser.js");

app.commandLine.appendSwitch("host-resolver-rules", "MAP source.example 127.0.0.1");
app.commandLine.appendSwitch("no-proxy-server");
const timeout = setTimeout(() => { console.error("Source browser smoke timed out"); app.exit(1); }, 30000);
void app.whenReady().then(async () => {
  for (const url of ["javascript:alert(1)", "file:///private", "http://localhost:8000", "http://127.0.0.1", "http://[::1]", "http://2130706433", "https://user:password@example.com", "http://service.local"]) assert.equal(isSourceUrl(url), false, url);
  assert.equal(isSourceUrl("https://example.com/report.pdf"), true);
  assert.deepEqual(sourceBounds({ x: -10, y: 20, width: 900, height: 900 }, 800, 600), { x: 0, y: 20, width: 800, height: 580 });
  assert.throws(() => sourceBounds({ x: NaN }, 800, 600));

  const requests = [];
  const server = http.createServer((request, response) => {
    requests.push({ url: request.url, authorization: request.headers.authorization, cookie: request.headers.cookie });
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
  await view.webContents.executeJavaScript("document.getElementById('next').click()");
  await waitForPage("Next source");
  assert.equal(view.webContents.navigationHistory.canGoBack(), true);
  await window.webContents.executeJavaScript("window.vibeDesktop.sourceBrowser.navigate('back')");
  await waitForPage("Source page");
  assert.equal(await window.webContents.executeJavaScript("document.title"), "Chat harness");
  await window.webContents.executeJavaScript("window.vibeDesktop.sourceBrowser.close()");
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.ok(sourceContents.isDestroyed());
  window.destroy();
  server.close();
  clearTimeout(timeout);
  console.log("Source browser smoke passed: frame-blocked page, navigation, isolated cookies/auth, no bridge, close cleanup");
  app.exit(0);
}).catch((error) => { console.error(error); clearTimeout(timeout); app.exit(1); });
