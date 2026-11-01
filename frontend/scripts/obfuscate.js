const fs = require("fs");
const path = require("path");
const JavaScriptObfuscator = require("javascript-obfuscator");

// BUILD_PATH: same variable react-scripts build uses (the e2e tests build into build-e2e)
const buildPath = path.resolve(__dirname, "..", process.env.BUILD_PATH || "build", "static/js");

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
