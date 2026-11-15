const fs = require("fs");
const path = require("path");
const JavaScriptObfuscator = require("javascript-obfuscator");

// BUILD_PATH: same variable react-scripts build uses (the e2e tests build into build-e2e)
const buildPath = path.resolve(__dirname, "..", process.env.BUILD_PATH || "build", "static/js");

// Vite's own preload helper (vite.config.mjs puts it in preload-helper-*.js): public code, and
// obfuscating it next to other code sometimes broke it (lazy pages failed to load: blank page)
const KEEP_AS_IS = /^preload-helper-/;

fs.readdirSync(buildPath).forEach(file => {
  if (!file.endsWith(".js")) return;
  if (KEEP_AS_IS.test(file)) {
    console.log("Left as is:", file);
    return;
  }

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
