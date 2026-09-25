-- =============================================================================
-- RFM_ValidateProductName - PolkaSQL / SQL Anywhere 17.0.11.7908 (Watcom-SQL)
-- =============================================================================
-- Validates that a catalog (folder) name pushed from RFM corresponds to a real
-- product, matching Polka27.elementy.grup_nazwe_kolor. On a match it returns that
-- name as matched_name, which RFM sends to PIM as both tgId and imageCatalog.
-- On a miss it returns the closest names ranked by similarity so the operator
-- can correct the folder.
--
--   grup_nazwe_kolor (matched_name, tgId) : 'TORBA HB0788 FA0542-910 SILVER'
--   grup_nazwe       (tg_id, unused)      : 'TORBA HB0788 FA0542'
--
-- The tg_id field (grup_nazwe) is not what PIM expects; RFM ignores it.
--
-- AAA follows the same simplified pattern as RFM_sp_Auth: a hardcoded API key
-- allow-list, explicit input validation, and a single JSON result column.
--
-- Deploy in two parts:
--   1. the procedure below
--   2. the web service definition at the end of this file
-- =============================================================================

-- -----------------------------------------------------------------------------
-- PART 1 - Procedure
-- -----------------------------------------------------------------------------
-- Use CREATE PROCEDURE for the first deployment, ALTER PROCEDURE afterwards.

ALTER PROCEDURE "Polka27"."RFM_sp_ValidateProductName"(
  IN ApiKey CHAR(37),
  IN CatalogName VARCHAR(200),
  IN MaxSuggestions INT DEFAULT 5
)
RESULT (json_response LONG VARCHAR)
BEGIN
  DECLARE v_name            VARCHAR(200);
  DECLARE v_matched         VARCHAR(200);
  DECLARE v_tg_id           VARCHAR(200);
  DECLARE v_product_id      INT;
  DECLARE v_max             INT;
  DECLARE v_count           INT;
  DECLARE v_first_token     VARCHAR(100);
  DECLARE v_space_pos       INT;
  DECLARE v_suggestions     LONG VARCHAR;
  DECLARE json_result       LONG VARCHAR;

  SET v_suggestions = '';
  SET v_product_id  = NULL;
  SET v_matched     = NULL;
  SET v_tg_id       = NULL;

  -- ---------------------------------------------------------------------------
  -- API KEY VALIDATION
  -- ---------------------------------------------------------------------------
  IF ApiKey IS NULL OR ApiKey = '' OR
     ApiKey NOT IN ('topsecret1', 'topsecret2') THEN
    SET json_result = '{"success": false, "valid": false, "error": "Invalid or missing API key"}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;

  -- ---------------------------------------------------------------------------
  -- INPUT VALIDATION
  -- ---------------------------------------------------------------------------
  IF CatalogName IS NULL OR TRIM(CatalogName) = '' THEN
    SET json_result = '{"success": false, "valid": false, "error": "CatalogName is required"}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;

  SET v_name = TRIM(CatalogName);

  -- Clamp the suggestion count to a sane range
  IF MaxSuggestions IS NULL OR MaxSuggestions < 1 THEN
    SET v_max = 5;
  ELSEIF MaxSuggestions > 25 THEN
    SET v_max = 25;
  ELSE
    SET v_max = MaxSuggestions;
  END IF;

  -- ---------------------------------------------------------------------------
  -- EXACT MATCH
  -- ---------------------------------------------------------------------------
  -- Comparison follows the database collation, which is case-insensitive on
  -- this instance, matching the case-insensitive behaviour of RFM_sp_Auth.
  -- Every size row of a product shares grup_nazwe_kolor and grup_nazwe, so
  -- the first row by Indeks is as good as any.
  SELECT FIRST e.Indeks, e.grup_nazwe_kolor, e.grup_nazwe
    INTO v_product_id, v_matched, v_tg_id
    FROM Polka27.elementy e
   WHERE e.grup_nazwe_kolor = v_name
   ORDER BY e.Indeks;

  IF v_product_id IS NOT NULL THEN
    SET json_result =
      '{' ||
        '"success": true,' ||
        '"valid": true,' ||
        '"error": null,' ||
        '"catalog_name": "' || REPLACE(REPLACE(v_name, '\', '\\'), '"', '\"') || '",' ||
        '"matched_name": "' || REPLACE(REPLACE(v_matched, '\', '\\'), '"', '\"') || '",' ||
        '"product_id": ' || CAST(v_product_id AS VARCHAR) || ',' ||
        '"tg_id": ' ||
          IF v_tg_id IS NULL OR TRIM(v_tg_id) = '' THEN 'null'
          ELSE '"' || REPLACE(REPLACE(TRIM(v_tg_id), '\', '\\'), '"', '\"') || '"'
          ENDIF || ',' ||
        '"suggestions": []' ||
      '}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;

  -- ---------------------------------------------------------------------------
  -- NO EXACT MATCH - BUILD SUGGESTIONS
  -- ---------------------------------------------------------------------------
  -- Pre-filter on the first whitespace-delimited token (e.g. 'TORBA') to keep
  -- the SIMILAR() scan off the full elementy table, then rank by similarity.
  SET v_space_pos = LOCATE(v_name, ' ');
  IF v_space_pos > 1 THEN
    SET v_first_token = LEFT(v_name, v_space_pos - 1);
  ELSE
    SET v_first_token = v_name;
  END IF;

  SET v_count = 0;

  sugloop: FOR sug AS sugcur CURSOR FOR
    -- GROUP BY rather than DISTINCT: SQL Anywhere refuses ORDER BY on a column
    -- outside a DISTINCT select list, which failed every miss with "Function
    -- or column reference to 's_score' in the ORDER BY clause is invalid".
    -- All size rows of a name have the same score, so MAX() is that score.
    SELECT s_name, MAX(s_score) AS s_best
      FROM (
        SELECT e.grup_nazwe_kolor AS s_name,
               SIMILAR(e.grup_nazwe_kolor, v_name) AS s_score
          FROM Polka27.elementy e
         WHERE e.grup_nazwe_kolor IS NOT NULL
           AND e.grup_nazwe_kolor <> ''
           AND e.Key1_i = 'A'
           AND ( e.grup_nazwe_kolor LIKE v_first_token || '%'
              OR SIMILAR(e.grup_nazwe_kolor, v_name) >= 60 )
      ) AS scored
     WHERE s_score >= 40
     GROUP BY s_name
     ORDER BY s_best DESC, s_name ASC
  DO
    IF v_count >= v_max THEN
      LEAVE sugloop;
    END IF;

    IF v_count > 0 THEN
      SET v_suggestions = v_suggestions || ', ';
    END IF;

    SET v_suggestions = v_suggestions ||
      '"' || REPLACE(REPLACE(s_name, '\', '\\'), '"', '\"') || '"';

    SET v_count = v_count + 1;
  END FOR;

  SET json_result =
    '{' ||
      '"success": true,' ||
      '"valid": false,' ||
      '"error": null,' ||
      '"catalog_name": "' || REPLACE(REPLACE(v_name, '\', '\\'), '"', '\"') || '",' ||
      '"matched_name": null,' ||
      '"product_id": null,' ||
      '"tg_id": null,' ||
      '"suggestions": [' || v_suggestions || ']' ||
    '}';

  SELECT json_result AS json_response;

EXCEPTION WHEN OTHERS THEN
  SET json_result =
    '{"success": false, "valid": false, "error": "' ||
    REPLACE(REPLACE(ERRORMSG(), '\', '\\'), '"', '\"') || '"}';
  SELECT json_result AS json_response;

END;

COMMENT ON PROCEDURE "Polka27"."RFM_sp_ValidateProductName" IS 'Procedura walidacji nazwy produktu dla aplikacji RFM (ff.vitkac.local).
Waliduje klucz API oraz nazwę katalogową produktu, a następnie wyszukuje dokładne dopasowanie w tabeli Polka27.elementy. W przypadku znalezienia dopasowania zwraca nazwę produktu, jego product_id (Indeks) oraz tg_id. Jeżeli dokładne dopasowanie nie zostanie znalezione, generuje listę podobnych nazw produktów na podstawie pierwszego tokenu nazwy oraz podobieństwa tekstowego (SIMILAR), ograniczając wynik do zadanej liczby sugestii.
Zwraca JSON z polami: success, valid, error, catalog_name, matched_name, product_id, tg_id, suggestions.
Liczba sugestii jest ograniczana do zakresu 1–25 (domyślnie 5), a dopasowanie nazwy produktu respektuje kolację bazy danych. W przypadku błędu wykonania procedura zwraca komunikat błędu w formacie JSON.';


-- -----------------------------------------------------------------------------
-- PART 2 - Web Service
-- -----------------------------------------------------------------------------
-- Deployed once; a procedure change needs only PART 1.
--
-- Character set: SQL Anywhere sends the body in the database charset and says
-- so (Content-Type: text/plain; charset=windows-1250, 'Ę' = byte 0xCA).
-- RFM must NOT send Accept-Charset: with "Accept-Charset: utf-8" the exact
-- match failed for 'RĘKAWICZKI 104458 0-12L' (backend/api/services/polka.py).

CREATE SERVICE "RFM_ValidateProductName"
  TYPE 'RAW'
  AUTHORIZATION OFF
  USER "RFM_view"
  METHODS 'GET'
  AS CALL "Polka27"."RFM_sp_ValidateProductName"(:ApiKey, :CatalogName, :MaxSuggestions);

COMMENT ON SERVICE "RFM_ValidateProductName" IS 'Web service pozwalający na zdalną walidację nazwy produktu w aplikacji RFM (ff.vitkac.local).
Wywołuje procedurę Polka27.RFM_sp_ValidateProductName.
Waliduje klucz API oraz nazwę katalogową produktu i zwraca dokładne dopasowanie lub listę podobnych nazw produktów.
Zwraca JSON: {"success": true/false, "valid": true/false, "error": null/"message", "catalog_name": "name", "matched_name": "name"/null, "product_id": 123/null, "tg_id": "id"/null, "suggestions": ["name1", "name2"]}.
Liczba sugestii jest ograniczana do zakresu 1–25 (domyślnie 5). Dopasowanie nazwy respektuje kolację bazy danych.';


-- -----------------------------------------------------------------------------
-- Verification
-- -----------------------------------------------------------------------------
-- Exact match (expect valid: true, product_id 2473757):
--   CALL "Polka27"."RFM_sp_ValidateProductName"('topsecret1', 'TORBA HB0788 FA0542-910 SILVER', 5);
--
-- Exact match (expect matched_name "OZDOBA PS261403 0-BRASS"):
--   CALL "Polka27"."RFM_sp_ValidateProductName"('topsecret1', 'OZDOBA PS261403 0-BRASS', 5);
--
-- Polish letter (expect valid: true, product_id 2490156):
--   CALL "Polka27"."RFM_sp_ValidateProductName"('topsecret1', 'RĘKAWICZKI 104458 0-12L', 5);
--
-- Near miss (expect valid: false with suggestions, not the 's_score' ORDER BY error):
--   CALL "Polka27"."RFM_sp_ValidateProductName"('topsecret1', 'TORBA HB0788 FA0542-910 SILVR', 5);
--
-- Bad key (expect success: false):
--   CALL "Polka27"."RFM_sp_ValidateProductName"('nope', 'TORBA HB0788 FA0542-910 SILVER', 5);
--
-- Over HTTP:
--   GET http://<host>:<port>/RFM_ValidateProductName
--         ?ApiKey=topsecret1
--         &CatalogName=TORBA%20HB0788%20FA0542-910%20SILVER
--         &MaxSuggestions=5
