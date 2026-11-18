/**
 * Node-RED settings for the local demo environment (see docker-compose.yml).
 * Only the values that differ from Node-RED's defaults are set here.
 */
module.exports = {
    flowFile: "flows.json",
    flowFilePretty: true,

    // The demo database password in flows_cred.json is stored unencrypted so the demo
    // runs out of the box. Use a secret here (and never commit flows_cred.json) for real data.
    credentialSecret: false,

    uiPort: process.env.PORT || 1880,
    diagnostics: { enabled: false, ui: false },
    runtimeState: { enabled: false, ui: false },
    logging: { console: { level: "info", metrics: false, audit: false } },
    editorTheme: { projects: { enabled: false }, tours: false },
    functionExternalModules: false,
    exportGlobalContextKeys: false,
};
