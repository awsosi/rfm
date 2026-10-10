-- =============================================================================
-- RFM_ProductDetails - PolkaSQL / SQL Anywhere 17.0.11.7908 (Watcom-SQL)
-- =============================================================================
-- Product data for the RFM classification reports (Raport_klasyfikacji_*.xlsx):
-- one catalog (folder) name in, the product's report fields out. RFM calls it
-- once per catalog pushed in the reported period.
--
-- The catalog name is Polka27.elementy.grup_nazwe_kolor, exactly as matched by
-- RFM_ValidateProductName.
--
-- Response:
--   {"success": true, "found": true, "error": null,
--    "catalog_name": "TORBA HB0788 FA0542-910 SILVER",
--    "product": {"designer": "...", "gender": "...",
--                "release_date": "2026-09-30", "last_send_date": "2026-10-02"}}
--
-- Every key of "product" can be shown in a report column as product.<key>
-- (Admin Panel -> Configuration -> Classification Reports -> Columns). A new
-- field needs only a new key here, no RFM release. Dates must be ISO
-- (YYYY-MM-DD, optionally with a time) so Excel gets real dates; RFM compares
-- product.release_date with the day the folder was pushed to colour late rows.
--
-- !!! TO CHECK BEFORE DEPLOYING !!!
-- The source columns of designer, gender, release_date and last_send_date
-- below (marked "MAP:") are placeholders: replace them with the real Polka27
-- columns or joins. Everything else follows RFM_sp_ValidateProductName.
--
-- Deploy in two parts:
--   1. the procedure below
--   2. the web service definition at the end of this file
-- Then set in RFM Admin Panel -> Classification Reports:
--   Product details URL = http://<host>:<port>/RFM_ProductDetails
--   Product details API key = one of the keys allowed below
-- =============================================================================

-- -----------------------------------------------------------------------------
-- PART 1 - Procedure
-- -----------------------------------------------------------------------------
-- Use CREATE PROCEDURE for the first deployment, ALTER PROCEDURE afterwards.

CREATE PROCEDURE "Polka27"."RFM_sp_ProductDetails"(
  IN ApiKey CHAR(37),
  IN CatalogName VARCHAR(200)
)
RESULT (json_response LONG VARCHAR)
BEGIN
  DECLARE v_name            VARCHAR(200);
  DECLARE v_product_id      INT;
  DECLARE v_designer        VARCHAR(200);
  DECLARE v_gender          VARCHAR(100);
  DECLARE v_release_date    DATE;
  DECLARE v_last_send_date  DATE;
  DECLARE json_result       LONG VARCHAR;

  SET v_product_id = NULL;

  -- ---------------------------------------------------------------------------
  -- API KEY VALIDATION
  -- ---------------------------------------------------------------------------
  IF ApiKey IS NULL OR ApiKey = '' OR
     ApiKey NOT IN ('topsecret1', 'topsecret2') THEN
    SET json_result = '{"success": false, "found": false, "error": "Invalid or missing API key"}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;

  -- ---------------------------------------------------------------------------
  -- INPUT VALIDATION
  -- ---------------------------------------------------------------------------
  IF CatalogName IS NULL OR TRIM(CatalogName) = '' THEN
    SET json_result = '{"success": false, "found": false, "error": "CatalogName is required"}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;

  SET v_name = TRIM(CatalogName);

  -- ---------------------------------------------------------------------------
  -- LOOKUP
  -- ---------------------------------------------------------------------------
  -- Every size row of a product shares grup_nazwe_kolor; the first row by
  -- Indeks carries the product-level fields.
  SELECT FIRST
         e.Indeks,
         e.projektant,         -- MAP: designer
         e.plec,               -- MAP: gender
         e.data_premiery,      -- MAP: release date
         e.data_ost_wysylki    -- MAP: last send date
    INTO v_product_id, v_designer, v_gender, v_release_date, v_last_send_date
    FROM Polka27.elementy e
   WHERE e.grup_nazwe_kolor = v_name
   ORDER BY e.Indeks;

  IF v_product_id IS NULL THEN
    SET json_result =
      '{"success": true, "found": false, "error": null, "catalog_name": "' ||
      REPLACE(REPLACE(v_name, '\', '\\'), '"', '\"') || '", "product": null}';
    SELECT json_result AS json_response;
    RETURN;
  END IF;

  SET json_result =
    '{' ||
      '"success": true,' ||
      '"found": true,' ||
      '"error": null,' ||
      '"catalog_name": "' || REPLACE(REPLACE(v_name, '\', '\\'), '"', '\"') || '",' ||
      '"product": {' ||
        '"product_id": ' || CAST(v_product_id AS VARCHAR) || ',' ||
        '"designer": ' ||
          IF v_designer IS NULL OR TRIM(v_designer) = '' THEN 'null'
          ELSE '"' || REPLACE(REPLACE(TRIM(v_designer), '\', '\\'), '"', '\"') || '"'
          ENDIF || ',' ||
        '"gender": ' ||
          IF v_gender IS NULL OR TRIM(v_gender) = '' THEN 'null'
          ELSE '"' || REPLACE(REPLACE(TRIM(v_gender), '\', '\\'), '"', '\"') || '"'
          ENDIF || ',' ||
        '"release_date": ' ||
          IF v_release_date IS NULL THEN 'null'
          ELSE '"' || DATEFORMAT(v_release_date, 'yyyy-mm-dd') || '"'
          ENDIF || ',' ||
        '"last_send_date": ' ||
          IF v_last_send_date IS NULL THEN 'null'
          ELSE '"' || DATEFORMAT(v_last_send_date, 'yyyy-mm-dd') || '"'
          ENDIF ||
      '}' ||
    '}';

  SELECT json_result AS json_response;

EXCEPTION WHEN OTHERS THEN
  SET json_result =
    '{"success": false, "found": false, "error": "' ||
    REPLACE(REPLACE(ERRORMSG(), '\', '\\'), '"', '\"') || '"}';
  SELECT json_result AS json_response;

END;

COMMENT ON PROCEDURE "Polka27"."RFM_sp_ProductDetails" IS 'Procedura danych produktu dla raportów klasyfikacji aplikacji RFM (ff.vitkac.local).
Waliduje klucz API, wyszukuje produkt po nazwie katalogowej (Polka27.elementy.grup_nazwe_kolor) i zwraca pola raportu: projektant, płeć, data premiery, data ostatniej wysyłki.
Zwraca JSON z polami: success, found, error, catalog_name, product. Daty w formacie yyyy-mm-dd. W przypadku błędu zwraca komunikat w formacie JSON.';


-- -----------------------------------------------------------------------------
-- PART 2 - Web Service
-- -----------------------------------------------------------------------------
-- Same character set rules as RFM_ValidateProductName: RFM must not send
-- Accept-Charset (backend/api/services/polka.py).

CREATE SERVICE "RFM_ProductDetails"
  TYPE 'RAW'
  AUTHORIZATION OFF
  USER "RFM_view"
  METHODS 'GET'
  AS CALL "Polka27"."RFM_sp_ProductDetails"(:ApiKey, :CatalogName);

COMMENT ON SERVICE "RFM_ProductDetails" IS 'Web service danych produktu dla raportów klasyfikacji aplikacji RFM (ff.vitkac.local).
Wywołuje procedurę Polka27.RFM_sp_ProductDetails.
Zwraca JSON: {"success": true/false, "found": true/false, "error": null/"message", "catalog_name": "name", "product": {"designer", "gender", "release_date", "last_send_date"}/null}.';


-- -----------------------------------------------------------------------------
-- Verification
-- -----------------------------------------------------------------------------
-- Known product (expect found: true and the four fields):
--   CALL "Polka27"."RFM_sp_ProductDetails"('topsecret1', 'TORBA HB0788 FA0542-910 SILVER');
--
-- Unknown name (expect success: true, found: false):
--   CALL "Polka27"."RFM_sp_ProductDetails"('topsecret1', 'NO SUCH PRODUCT');
--
-- Bad key (expect success: false):
--   CALL "Polka27"."RFM_sp_ProductDetails"('nope', 'TORBA HB0788 FA0542-910 SILVER');
--
-- Over HTTP:
--   GET http://<host>:<port>/RFM_ProductDetails
--         ?ApiKey=topsecret1
--         &CatalogName=TORBA%20HB0788%20FA0542-910%20SILVER
