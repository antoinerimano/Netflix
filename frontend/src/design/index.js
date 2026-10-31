// src/design/index.js
// Design system entry: imported first in src/index.js so every page style can use the tokens.
import "./tokens.css";
import "./base.css";
import "./components.css";

export * from "./components";
export * as Icons from "./icons";

// TV browsers get the larger "10-foot" scale (tokens.css: html.tv-device)
const TV_UA = /SMART-TV|SmartTV|Tizen|Web0S|webOS|NetCast|BRAVIA|AFT[A-Z]|Android TV|GoogleTV|HbbTV|CrKey|Roku|VIDAA/i;
if (typeof navigator !== "undefined" && TV_UA.test(navigator.userAgent || "")) {
  document.documentElement.classList.add("tv-device");
}
