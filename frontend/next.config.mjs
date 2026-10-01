/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV !== "production";
// In dev, proxy /api/* to the FastAPI backend so the app stays same-origin.
// Rewrites are incompatible with static export, so they only exist in dev.
const backend = process.env.FINALLY_BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig = {
  output: isDev ? undefined : "export",
  trailingSlash: false,
  images: { unoptimized: true },
  reactStrictMode: true,
  ...(isDev
    ? {
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
        },
      }
    : {}),
};

export default nextConfig;
