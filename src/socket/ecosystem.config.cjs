// eslint-disable-next-line no-undef
module.exports = {
    apps: [
        {
            name: "langboard",
            script: "./dist/index.js",
            instances: 1,
            exec_mode: "fork",
            watch: false,
            kill_timeout: 900000,
        },
    ],
};
