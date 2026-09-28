This repository on its own does nothing, as it is missing the SQL database with the actual statistics and my Moxfield API key for deck visualization.
It is here publicly so that anyone interested can view the code that went into it, and suggest features, fixes, or general improvements.
To access, please view the primary site vvmtg.com, and join the Value Vintage Discord server if you haven’t already.

Data collection began Jan 4, 2026. All data collection and entry was done manually by myself (vividplasma) and Forkpapi. Mistakes are possible; if you see any please notify one of us. Decklists were assigned new or existing archetypes based on format awareness. If you feel any are miscategorized, likewise please alert one of us.

# Features:

## Archetype Information:
* See all 392 and counting tracked deck archetypes
* Filter by primary color(s), either at most, least, or exactly
* Filter by Style (Aggro, Midrange, Control, Combo, Prison)
* Filter only archetypes with a minimum number of appearances
* Sort archetypes by:
  * Alphabetical, Win Rate, Play Rate, Newest Added, and Most Recently Played
  * Either by All Time or data from the last 3 months
* For each, see its:
  * Win - Loss - Draw record
  * Bayesian adjusted score (so that a 64-7 deck outranks a 3-0 deck)
  * Number of entries
  * Matchup data vs other archetypes
  * Recent tournament results
  * Average card frequency split by mainboard and sideboard
  * Top players (limited to public profiles, see Players section)
 
## Player Information:
* Every player ordered by Bayesian adjusted W-L rank
* Any provided social links / bio
* Non-public profiles are limited to the above. Profiles are private by default. You can request yours be made public or private.
* Public profiles additionally display:
* Exact total W-L record
* W-L stats by archetype played
* Number of times played for each archetype played
* Full tournament history (sort by newest, oldest, best record, or worst)
* Trophy Case:
  * All podium placements (top 3 small event, or top 8 large event)
  * All archetypes pioneered (first to play, didn’t exist prior to 2026 data)
  * Archetype Diversity trophy for number of distinct archetypes played
  * Archetype Loyalty trophies for number of instances playing with the same archetype
* Of note: **Your ranking is not an end-all determination of your skill as a player.** Frequent brewers tend to have lower winrates on average, and people just enjoy playing non-meta decks which by their nature tend to fare worse. The rankings are for curiosity purposes only (and maybe a bit of competition), but should not be treated as anything besides one number, which is also impacted by cutoffs in the Bayesian calculations.

## Card Information:
* See all played cards in the VV format
* Sort played cards by:
* * Alphabetical, Price (current), Win Rate, Adj. Win Rate (accounting for the number of copies in the deck), total appearances across all decks, how frequently it is played in some number across all decks (prevalence), and newest seen
  * Filter further by All Time data or past 30 days
  * Filter further by an optional minimum necessary number of appearances
  * Optionally exclude data contributions from banned Archetypes (Nadu decks)
* Also see the date the card was first recorded, how many archetypes it is present in, and how many submitted decks include it
* For a specific card searched, further see its popularity across each archetype it has appeared in via number of decks of that archetype, average copies mainboard, and average copies sideboard.
* Further see its price history from the last 30 days.

## Deck Visualization:
* Enter a Moxfield URL to see a price graph of all its cards, extending back 7 or 30 days, optionally excluding cards under $0.30, and sorting the cards either by name or price.
* If the decklist is recorded as having been played, see the price of the deck when it was played (if able). You must use the link present for that deck on the site. For weekly MTGO events these will be the TOBot links, for paper events these will be saved copies of the original lists, and can be acquired from the Tournament page they are listed in.

## Tournament Information:
* See all recorded tournaments, including date and gameplay format (Paper, MTGO, Cockatrice, Webcam, or Endstep)
* Filter by format, name, or date range.
* For a specific tournament:
* * See all final standings, including Player, Archetype, and link to decklist
  * Additionally, for MTGO events Aug onward, see full recap of round by round results.
