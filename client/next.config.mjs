/** @type {import('next').NextConfig} */
const nextConfig = {
  // The chat route spawns python subprocesses; tell Next not to bundle
  // node-only modules into the edge runtime.
  serverExternalPackages: [],
};

export default nextConfig;
