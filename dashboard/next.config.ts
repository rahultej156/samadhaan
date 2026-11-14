import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Off on purpose. This dashboard wants a plain `export const revalidate = 3`
  // on the operations page — poll the database every 3s, because there is no
  // browser-side Supabase key and therefore no Realtime subscription.
  cacheComponents: false,
  reactCompiler: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
