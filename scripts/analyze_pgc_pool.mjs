console.warn(
  "Deprecated: analyze_pgc_pool.mjs used non-raw fields in earlier versions. Running raw-event analysis instead.",
);

await import("./analyze_pgc_raw_events.mjs");
