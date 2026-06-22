# Newsbot Sources

This file tracks the currently configured sources in `config.yaml`.

## Current Free Sources

| Source name            | Type                            |                                                                             URL | Poll interval | Purpose                        | Notes                                                                    |
| ---------------------- | ------------------------------- | ------------------------------------------------------------------------------: | ------------: | ------------------------------ | ------------------------------------------------------------------------ |
| `chp_bay_area`         | `chp_html`                      |                            `https://m.chp.ca.gov/incident.aspx?DispatchId=GGCC` |           60s | Bay Area CHP traffic incidents | Public CHP mobile incident page. Good for collisions, hazards, closures. |
| `nws_south_bay_alerts` | `nws_alerts`                    |                 `https://api.weather.gov/alerts/active?point=37.3382,-121.8863` |          120s | Weather alerts near San Jose   | Official NWS API. Requires a clear User-Agent.                           |
| `usgs_all_hour`        | `usgs_geojson`                  |    `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson` |           60s | Earthquake feed                | Filtered locally to 50 miles around San Jose and magnitude >= 3.0.       |
| `calfire_active`       | `calfire_json`                  |     `https://incidents.fire.ca.gov/umbraco/api/IncidentApi/List?inactive=false` |          300s | Active wildfire incidents      | Filtered locally to nearby counties.                                     |
| `visa_bulletin`        | `html_page`                     | `https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html` |        21600s | Visa Bulletin                  | HTML page diff/new-item tracking only in the MVP.                        |
| `ca_warn`              | `warn_xlsx`                     |  `https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx` |        21600s | CA WARN layoff notices         | Parses the official XLSX report.                                         |
| `reddit_sanjose`       | `reddit_json` with RSS fallback |                            `https://www.reddit.com/r/SanJose/new.json?limit=50` |          300s | San Jose local social signal   | Reddit JSON often returns 403; code falls back to `/new/.rss`.           |
| `reddit_bayarea`       | `reddit_json` with RSS fallback |                            `https://www.reddit.com/r/bayarea/new.json?limit=50` |          300s | Bay Area social signal         | Same Reddit fallback behavior.                                           |
| `reddit_cupertino`     | `reddit_json` with RSS fallback |                          `https://www.reddit.com/r/cupertino/new.json?limit=50` |          300s | Cupertino social signal        | Same Reddit fallback behavior.                                           |
| `reddit_santaclara`    | `reddit_json` with RSS fallback |                         `https://www.reddit.com/r/SantaClara/new.json?limit=50` |          300s | Santa Clara social signal      | Same Reddit fallback behavior.                                           |
| `reddit_h1b`           | `reddit_json` with RSS fallback |                                `https://www.reddit.com/r/h1b/new.json?limit=50` |          900s | H1B discussion signal          | No official verification; treat as social signal.                        |
| `reddit_uscis`         | `reddit_json` with RSS fallback |                              `https://www.reddit.com/r/USCIS/new.json?limit=50` |          900s | USCIS discussion signal        | No official verification; treat as social signal.                        |
| `reddit_layoffs`       | `reddit_json` with RSS fallback |                            `https://www.reddit.com/r/layoffs/new.json?limit=50` |          900s | Layoff discussion signal       | No official verification; treat as social signal.                        |
| `sanjose_spotlight`    | `rss`                           |                                            `https://sanjosespotlight.com/feed/` |          600s | Local news RSS                 | Local news source.                                                       |
| `kqed_news`            | `rss`                           |                                             `https://ww2.kqed.org/news/feed/` |          600s | Bay Area public media news     | Summarized in Simplified Chinese before Telegram.                        |
| `kron4`                | `rss`                           |                                                  `https://www.kron4.com/feed/` |          600s | Bay Area TV news               | Summarized in Simplified Chinese before Telegram.                        |
| `abc7_bay_area`        | `rss`                           |                                                     `https://abc7news.com/feed/` |          600s | Bay Area TV news               | Summarized in Simplified Chinese before Telegram.                        |
| `nbc_bay_area`         | `rss`                           |                                          `https://www.nbcbayarea.com/?rss=y` |          600s | Bay Area TV news               | Summarized in Simplified Chinese before Telegram.                        |
| `cbs_bay_area_local`   | `rss`                           |             `https://www.cbsnews.com/sanfrancisco/latest/rss/local-news` |          600s | Bay Area local TV news         | Summarized in Simplified Chinese before Telegram.                        |
| `sfgate_bay_area`      | `rss`                           |                  `https://www.sfgate.com/bayarea/feed/Bay-Area-News-429.php` |          600s | Bay Area news                  | Summarized in Simplified Chinese before Telegram.                        |
| `berkeleyside`         | `rss`                           |                                             `https://www.berkeleyside.org/feed` |          900s | East Bay local news            | Summarized in Simplified Chinese before Telegram.                        |
| `oaklandside`          | `rss`                           |                                                  `https://oaklandside.org/feed/` |          900s | Oakland local news             | Summarized in Simplified Chinese before Telegram.                        |
| `palo_alto_online`     | `rss`                           |                                          `https://www.paloaltoonline.com/feed/` |          900s | Peninsula local news           | Summarized in Simplified Chinese before Telegram.                        |
| `mountain_view_voice`  | `rss`                           |                                                `https://www.mv-voice.com/feed/` |          900s | Mountain View local news       | Summarized in Simplified Chinese before Telegram.                        |

## Fetch Limits And Risks

| Source family | Practical limit | Risk | Current mitigation |
|---|---|---|---|
| CHP public page | 60s is reasonable for personal use | HTML structure may change | Parser is tolerant; failures recorded in `source_state`. |
| NWS API | 120s is conservative | Must use User-Agent; avoid abusive polling | Configured User-Agent and low polling rate. |
| USGS GeoJSON | 60s is reasonable for all-hour feed | Mostly noise outside the Bay Area | Local filter: within 50 miles of San Jose and magnitude >= 3.0. |
| CAL FIRE API | 300s is reasonable | API shape may change | County filter and failure logging. |
| CA WARN XLSX | 6h is enough | Large file; no need for frequent polling | Low polling rate. |
| Visa Bulletin | 6h is enough | Page changes monthly, not minute-by-minute | Low polling rate. |
| Reddit public JSON/RSS | 5-15 min is safer | JSON can return 403; RSS can rate-limit or block | RSS fallback, low polling rate, dedupe. |
| RSS feeds | 10 min is usually safe | Feed outages or malformed XML | Feedparser handles common feed issues. |

## Notification Mode

Current default:

```yaml
notifications:
  notify_all_new_raw_items: true
  notify_raw_item_max_per_fetch: 30
```

This means every newly inserted raw item is pushed to the single Telegram bot,
before AI filtering. Duplicate content is suppressed by `raw_items.content_hash`
and `raw_item_notifications`.

The AI classifier still runs later for event clustering and digest logic.

## Source-Specific Notification Rules

- `chp_bay_area`: only reports incidents geocoded within 25 miles of San Jose.
  If geocoding succeeds, Telegram receives a rendered map PNG with a red marker.
- `usgs_all_hour`: only reports earthquakes within 50 miles of San Jose and
  magnitude >= 3.0.
- Reddit and RSS/local news items are summarized by local Ollama in Simplified
  Chinese before Telegram. The summarizer requests no thinking output and strips
  `<think>...</think>` defensively.

## China-Related Source Notes

Requested locations: Suzhou and Shenyang.

| Source family | Current usability | Notes |
|---|---|---|
| Weibo public hot/search pages | Not stable enough for this bot | Direct public probes returned 403 or visitor-verification redirects. Using login cookies would be brittle and account-risky. |
| Xiaohongshu/REDnote | Not stable enough for this bot | No reliable public RSS/API for ordinary-user posts. Scraping usually requires browser automation/login and is likely to break. |
| Public `rsshub.app` Weibo/Xiaohongshu routes | Currently unusable from this environment | Tested routes returned 403 cost-restriction messages. |
| Self-hosted RSSHub | Possible future option | Could be added later if you want to run an RSSHub service yourself and accept maintenance/route breakage. |
| Chinese official/local news websites | Possible but not yet enabled | More stable than social platforms, but less "ordinary people" signal. Need specific target sites or tested RSS/HTML routes. |
