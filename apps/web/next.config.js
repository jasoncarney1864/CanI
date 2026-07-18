/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle (.next/standalone) so the container image is a
  // minimal `node server.js` with only the deps it actually uses — no full node_modules.
  output: "standalone",
};

module.exports = nextConfig;
