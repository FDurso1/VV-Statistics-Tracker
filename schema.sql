PRAGMA foreign_keys = OFF;
DROP TABLE IF EXISTS deck_cards;
DROP TABLE IF EXISTS tournament_standings;
DROP TABLE IF EXISTS matches;
DROP TABLE IF EXISTS player_aliases;
DROP TABLE IF EXISTS archetype_search_aliases;
DROP TABLE IF EXISTS decks;
DROP TABLE IF EXISTS players;
DROP TABLE IF EXISTS archetypes;
DROP TABLE IF EXISTS tournaments;
DROP TABLE IF EXISTS cards;

CREATE TABLE players (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
    moxfield_username TEXT, discord_username TEXT, twitch_username TEXT, bio TEXT,
    is_public INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE player_aliases (alias_name TEXT PRIMARY KEY, player_id INTEGER NOT NULL REFERENCES players(id));
CREATE TABLE archetypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
    primary_colors TEXT, variant_of TEXT, style TEXT,
    unclaimable INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE archetype_search_aliases (
    archetype_id INTEGER NOT NULL REFERENCES archetypes(id),
    alias_text TEXT NOT NULL, PRIMARY KEY (archetype_id, alias_text)
);
CREATE TABLE decks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    archetype_id INTEGER NOT NULL REFERENCES archetypes(id),
    moxfield_url TEXT UNIQUE, name TEXT, date_added TEXT NOT NULL
);
CREATE TABLE cards (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, scryfall_id TEXT, first_seen_date TEXT NOT NULL);
CREATE TABLE deck_cards (deck_id INTEGER NOT NULL REFERENCES decks(id), card_id INTEGER NOT NULL REFERENCES cards(id), quantity INTEGER NOT NULL, mainboard_quantity INTEGER NOT NULL DEFAULT 0, sideboard_quantity INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (deck_id, card_id));
CREATE TABLE tournaments (id TEXT PRIMARY KEY, name TEXT NOT NULL, played_on TEXT NOT NULL, format TEXT NOT NULL CHECK (format IN ('MTGO','Cockatrice','Webcam','Paper')), venue TEXT);
CREATE TABLE tournament_standings (tournament_id TEXT NOT NULL REFERENCES tournaments(id), player_id INTEGER NOT NULL REFERENCES players(id), deck_id INTEGER NOT NULL REFERENCES decks(id), final_rank INTEGER NOT NULL, wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0, draws INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (tournament_id, player_id));
CREATE TABLE matches (id INTEGER PRIMARY KEY AUTOINCREMENT, tournament_id TEXT NOT NULL REFERENCES tournaments(id), round_number INTEGER NOT NULL, player_1_id INTEGER NOT NULL REFERENCES players(id), player_2_id INTEGER REFERENCES players(id), result TEXT NOT NULL CHECK (result = 'bye' OR result GLOB '[0-9]-[0-9]' OR result GLOB '[0-9]-[0-9]-[0-9]'));
CREATE INDEX idx_decks_archetype ON decks(archetype_id);
CREATE INDEX idx_matches_tournament ON matches(tournament_id);
CREATE INDEX idx_deck_cards_card ON deck_cards(card_id);
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS card_price_cache (card_name TEXT NOT NULL, price_date TEXT NOT NULL, price REAL NOT NULL, PRIMARY KEY (card_name, price_date));
CREATE INDEX IF NOT EXISTS idx_card_price_cache_date ON card_price_cache(price_date);