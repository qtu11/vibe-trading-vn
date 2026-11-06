import { copyFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";

await mkdir(new URL("../dist/", import.meta.url), { recursive: true });
await copyFile(
  new URL("../src/loading.html", import.meta.url),
  new URL("../dist/loading.html", import.meta.url),
);

const iconPng = new URL("../../../assets/icon.png", import.meta.url);
if (existsSync(iconPng)) {
  await copyFile(iconPng, new URL("../dist/icon.png", import.meta.url));
}

const iconIco = new URL("../release/.icon-ico/icon.ico", import.meta.url);
if (existsSync(iconIco)) {
  await copyFile(iconIco, new URL("../dist/icon.ico", import.meta.url));
}
