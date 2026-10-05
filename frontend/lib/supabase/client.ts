import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "http://rpimu0p693wyvj4gqur3qvrt.88.222.213.242.sslip.io";
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIiwiaWF0IjoxNzkwNjc1MjQwLCJleHAiOjE5NDgzNTUyNDB9._a4Lehy9CE3jFYdajzXfUNg3r8rYhtomzWam7U9U87I";
  return createBrowserClient(url, key);
}
