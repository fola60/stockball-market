# API Traders Module

## Purpose

Public, read-only standings: the leaderboard of the richest traders and each trader's
profile (net worth, holdings, and recent trades).

## Rules

- Net worth is cash plus holdings valued at current prices.
- Only active `USER` and `SYNTHETIC_TRADER` accounts are ranked. Bots are labelled `BOT` so
  people can tell them apart; admin and system accounts, such as the player-share reserve,
  are never shown.
- Only display names, holdings, and trades are public. Emails and handles are never exposed.
- Ranks are computed across all public traders, so filtering to people or bots does not
  change anyone's rank.
