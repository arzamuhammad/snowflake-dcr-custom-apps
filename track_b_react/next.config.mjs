/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // snowflake-sdk is a native Node module; keep it server-side only.
  experimental: {
    serverComponentsExternalPackages: ["snowflake-sdk"],
  },
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: false },
};

export default nextConfig;
