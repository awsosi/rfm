-- =============================================================================
-- RFM_ValidateProductName - PolkaSQL / SQL Anywhere 17.0.11.7908 (Watcom-SQL)
-- =============================================================================
-- Validates that a catalog (folder) name pushed from RFM corresponds to a real
-- product, matching Polka27.elementy.grup_nazwe_kolor. On a miss it returns the
-- closest names ranked by similarity so the operator can correct the folder.
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
  SELECT FIRST e.Indeks, e.grup_nazwe_kolor
    INTO v_product_id, v_matched
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
    SELECT DISTINCT s_name
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
     ORDER BY s_score DESC, s_name ASC
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
      '"suggestions": [' || v_suggestions || ']' ||
    '}';

  SELECT json_result AS json_response;

EXCEPTION WHEN OTHERS THEN
  SET json_result =
    '{"success": false, "valid": false, "error": "' ||
    REPLACE(REPLACE(ERRORMSG(), '\', '\\'), '"', '\"') || '"}';
  SELECT json_result AS json_response;

END;


-- -----------------------------------------------------------------------------
-- PART 2 - Web Service
-- -----------------------------------------------------------------------------
-- Mirrors the RFM_Auth service definition.
--
--   Service name : RFM_ValidateProductName
--   Service type : Raw
--   URL path     : Off
--   Methods      : GET
--   Comment      : Web service pozwalajacy na walidacje nazwy katalogu
--                  produktu w aplikacji RFM (ff.vitkac.local).
--                  Wywoluje procedure Polka27.RFM_sp_ValidateProductName.
--                  Zwraca JSON: {"success": true/false, "valid": true/false,
--                  "error": null/"message", "catalog_name": "...",
--                  "matched_name": null/"...", "product_id": null/123,
--                  "suggestions": ["...", "..."]}
--                  Porownanie jest case-insensitive.

CREATE SERVICE "RFM_ValidateProductName"
  TYPE 'RAW'
  AUTHORIZATION OFF
  USER "Polka27"
  METHODS 'GET'
  AS CALL "Polka27"."RFM_sp_ValidateProductName"(:ApiKey, :CatalogName, :MaxSuggestions);


-- -----------------------------------------------------------------------------
-- Verification
-- -----------------------------------------------------------------------------
-- Exact match (expect valid: true, product_id 2473757):
--   CALL "Polka27"."RFM_sp_ValidateProductName"('topsecret1', 'TORBA HB0788 FA0542-910 SILVER', 5);
--
-- Near miss (expect valid: false with suggestions):
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
