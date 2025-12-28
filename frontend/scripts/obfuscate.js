const fs = require("fs");
const path = require("path");
const JavaScriptObfuscator = require("javascript-obfuscator");

const buildPath = path.join(__dirname, "../build/static/js");

fs.readdirSync(buildPath).forEach(file => {
  if (!file.endsWith(".js")) return;

  const filePath = path.join(buildPath, file);
  const code = fs.readFileSync(filePath, "utf8");

  const obfuscated = JavaScriptObfuscator.obfuscate(code, {
    compact: true,
    controlFlowFlattening: true,
    controlFlowFlatteningThreshold: 0.75,
    deadCodeInjection: true,
    deadCodeInjectionThreshold: 0.4,
    stringArray: true,
    stringArrayEncoding: ["base64"],
    renameGlobals: false
  });

  fs.writeFileSync(filePath, obfuscated.getObfuscatedCode());
  console.log("Obfuscated:", file);
});
