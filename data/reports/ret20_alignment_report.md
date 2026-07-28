# ret20 Alignment Diagnostics

This report tests ret20 hypotheses against parsed DOCX labels and manual source-text targets.

Formula tested:

`ret = (price[t] / price[t-window] - 1) * 100`

Hypothesis dimensions:

- `price_field`: close/open/high/low
- `window`: 5 to 40 trading rows
- `signal_offset`: 0 means report-date trading row, -1 means previous trading row

- target rows: 556
- evaluated rows: 240192

## Best Hypotheses

### doc_rows / broad

| source   | module   | price_field   |   window |   signal_offset |   count |   mae |   rmse |   median_abs_error |   max_abs_error |
|:---------|:---------|:--------------|---------:|----------------:|--------:|------:|-------:|-------------------:|----------------:|
| doc_rows | broad    | close         |       23 |              -1 |     510 | 1.093 |  1.522 |              0.814 |          10.314 |
| doc_rows | broad    | close         |       24 |              -1 |     510 | 1.119 |  1.558 |              0.782 |           9.691 |
| doc_rows | broad    | low           |       23 |              -1 |     510 | 1.197 |  1.766 |              0.915 |          16.072 |
| doc_rows | broad    | close         |       25 |              -1 |     510 | 1.266 |  1.785 |              0.913 |           9.88  |
| doc_rows | broad    | low           |       24 |              -1 |     510 | 1.217 |  1.8   |              0.858 |          15.845 |
| doc_rows | broad    | close         |       22 |              -1 |     510 | 1.364 |  1.88  |              1.006 |          10.789 |
| doc_rows | broad    | open          |       24 |               0 |     510 | 1.272 |  1.924 |              0.835 |          12.723 |
| doc_rows | broad    | high          |       23 |              -1 |     510 | 1.326 |  1.943 |              0.926 |          13.212 |
| doc_rows | broad    | low           |       25 |               0 |     510 | 1.404 |  1.945 |              1.033 |          10.501 |
| doc_rows | broad    | low           |       25 |              -1 |     510 | 1.4   |  2.003 |              1.017 |          15.101 |

### manual / broad

| source   | module   | price_field   |   window |   signal_offset |   count |   mae |   rmse |   median_abs_error |   max_abs_error |
|:---------|:---------|:--------------|---------:|----------------:|--------:|------:|-------:|-------------------:|----------------:|
| manual   | broad    | close         |       24 |              -1 |      30 | 1.125 |  1.519 |              0.86  |           5.094 |
| manual   | broad    | close         |       24 |               0 |      30 | 1.072 |  1.524 |              0.838 |           4.483 |
| manual   | broad    | low           |       21 |              -1 |      30 | 1.168 |  1.534 |              0.852 |           4.566 |
| manual   | broad    | high          |       25 |               0 |      30 | 1.172 |  1.537 |              1.055 |           3.676 |
| manual   | broad    | low           |       27 |               0 |      30 | 1.208 |  1.563 |              0.985 |           3.662 |
| manual   | broad    | open          |       24 |               0 |      30 | 1.095 |  1.574 |              0.897 |           5.234 |
| manual   | broad    | low           |       24 |               0 |      30 | 1.043 |  1.615 |              0.767 |           5.985 |
| manual   | broad    | low           |       26 |               0 |      30 | 1.331 |  1.707 |              1.081 |           3.869 |
| manual   | broad    | high          |       24 |               0 |      30 | 1.175 |  1.738 |              0.758 |           5.254 |
| manual   | broad    | high          |       24 |              -1 |      30 | 1.274 |  1.777 |              1.06  |           5.743 |

### manual / market_index

| source   | module       | price_field   |   window |   signal_offset |   count |   mae |   rmse |   median_abs_error |   max_abs_error |
|:---------|:-------------|:--------------|---------:|----------------:|--------:|------:|-------:|-------------------:|----------------:|
| manual   | market_index | low           |       27 |               0 |      16 | 0.704 |  0.951 |              0.582 |           2.838 |
| manual   | market_index | high          |       25 |               0 |      16 | 1.082 |  1.463 |              1.095 |           4.281 |
| manual   | market_index | low           |       28 |               0 |      16 | 1.11  |  1.467 |              1.003 |           3.721 |
| manual   | market_index | low           |       20 |              -1 |      16 | 1.283 |  1.552 |              1.069 |           2.93  |
| manual   | market_index | close         |       28 |               0 |      16 | 1.309 |  1.552 |              1.138 |           2.747 |
| manual   | market_index | high          |       27 |               0 |      16 | 1.136 |  1.663 |              1.029 |           5.342 |
| manual   | market_index | high          |       26 |              -1 |      16 | 1.476 |  1.682 |              1.285 |           2.935 |
| manual   | market_index | close         |       19 |              -2 |      16 | 1.354 |  1.692 |              0.975 |           3.589 |
| manual   | market_index | close         |       22 |               0 |      16 | 1.328 |  1.713 |              0.97  |           4.052 |
| manual   | market_index | close         |       26 |              -1 |      16 | 1.405 |  1.726 |              1.052 |           4.096 |

## Current Strict Formula Snapshot

| source   | module       | price_field   |   window |   signal_offset |   count |   mae |   rmse |   median_abs_error |   max_abs_error |
|:---------|:-------------|:--------------|---------:|----------------:|--------:|------:|-------:|-------------------:|----------------:|
| doc_rows | broad        | close         |       20 |              -1 |     510 | 1.901 |  2.574 |              1.379 |          10.222 |
| manual   | broad        | close         |       20 |              -1 |      30 | 2.496 |  3.544 |              1.567 |           9.437 |
| manual   | market_index | close         |       20 |              -1 |      16 | 2.879 |  3.822 |              2.06  |           8.509 |

## Worst Rows For Strict Formula

| source   | module       | report_date   | signal_date   | base_date   | name   | code      |   target_ret20_pct |   predicted_ret20_pct |   error |
|:---------|:-------------|:--------------|:--------------|:------------|:-------|:----------|-------------------:|----------------------:|--------:|
| doc_rows | broad        | 2026-05-12    | 2026-05-11    | 2026-04-08  | 华宝油气   | 162411.SZ |              -12.1 |                 -1.88 |   10.22 |
| doc_rows | broad        | 2026-06-04    | 2026-06-03    | 2026-05-06  | 科创50   | 588000.SH |               14.1 |                  4.53 |   -9.57 |
| doc_rows | broad        | 2026-06-05    | 2026-06-04    | 2026-05-07  | 科创50   | 588000.SH |               13.1 |                  3.56 |   -9.54 |
| manual   | broad        | 2026-07-01    | 2026-06-30    | 2026-06-01  | 科创50   | 588000.SH |               24.2 |                 33.64 |    9.44 |
| manual   | market_index | 2026-07-01    | 2026-06-30    | 2026-06-01  | 科创50   | 000688.SH |               24.2 |                 32.71 |    8.51 |
| doc_rows | broad        | 2026-05-14    | 2026-05-13    | 2026-04-10  | 华宝油气   | 162411.SZ |              -10.4 |                 -2.1  |    8.3  |
| manual   | broad        | 2026-07-13    | 2026-07-09    | 2026-06-10  | 科创50   | 588000.SH |               25.2 |                 33.49 |    8.29 |
| doc_rows | broad        | 2026-05-18    | 2026-05-15    | 2026-04-14  | 创业板50  | 159949.SZ |               19.6 |                 11.43 |   -8.17 |
| doc_rows | broad        | 2026-06-05    | 2026-06-04    | 2026-05-07  | 日经225  | 513520.SH |               16   |                  7.99 |   -8.01 |
| manual   | broad        | 2026-07-13    | 2026-07-09    | 2026-06-10  | 创业板50  | 159949.SZ |               -4.9 |                  2.88 |    7.78 |
| doc_rows | broad        | 2026-05-19    | 2026-05-18    | 2026-04-15  | 华宝油气   | 162411.SZ |               -0   |                  7.38 |    7.38 |
| doc_rows | broad        | 2026-06-09    | 2026-06-08    | 2026-05-11  | 科创50   | 588000.SH |                0.3 |                 -7.07 |   -7.37 |
| doc_rows | broad        | 2026-05-12    | 2026-05-11    | 2026-04-08  | 纳指     | 513100.SH |               22.2 |                 15    |   -7.2  |
| manual   | broad        | 2026-07-01    | 2026-06-30    | 2026-06-01  | 纳指     | 513100.SH |                0.3 |                 -6.81 |   -7.11 |
| manual   | market_index | 2026-07-13    | 2026-07-09    | 2026-06-10  | 科创50   | 000688.SH |               25.2 |                 32.3  |    7.1  |
| doc_rows | broad        | 2026-06-11    | 2026-06-10    | 2026-05-13  | 科创50   | 588000.SH |                0.6 |                 -6.49 |   -7.09 |
| doc_rows | broad        | 2026-05-20    | 2026-05-19    | 2026-04-16  | 创业板50  | 159949.SZ |               15.1 |                  8.25 |   -6.85 |
| doc_rows | broad        | 2026-05-21    | 2026-05-20    | 2026-04-17  | 创业板50  | 159949.SZ |               13.7 |                  6.92 |   -6.78 |
| manual   | market_index | 2026-07-13    | 2026-07-09    | 2026-06-10  | 创业板    | 399006.SZ |               -2.5 |                  4.24 |    6.74 |
| doc_rows | broad        | 2026-05-14    | 2026-05-13    | 2026-04-10  | 创业板50  | 159949.SZ |               25.5 |                 18.83 |   -6.67 |

## Interpretation Checklist

- If one global hypothesis wins consistently, promote it to strategy config.
- If manual source-text samples want a different best hypothesis than historical DOCX rows, do not tune only to a single day.
- If no global hypothesis is stable, the remaining gap is likely source price data, adjusted series, or mixed field/date cutoffs.
