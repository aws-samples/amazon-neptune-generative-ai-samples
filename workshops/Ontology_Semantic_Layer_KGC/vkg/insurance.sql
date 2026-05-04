CREATE TABLE customer (
  id VARCHAR(20) PRIMARY KEY,
  customer_id VARCHAR(20) NOT NULL,
  customer_name VARCHAR(100) NOT NULL
);

CREATE TABLE policy (
  id VARCHAR(10) PRIMARY KEY,
  policy_id VARCHAR(20) NOT NULL,
  policy_type VARCHAR(10) NOT NULL,
  customer_id VARCHAR(20) NOT NULL REFERENCES customer(id)
);

CREATE TABLE policy_coverage (
  id VARCHAR(20) PRIMARY KEY,
  policy_id VARCHAR(10) NOT NULL REFERENCES policy(id),
  coverage_amount DECIMAL(12,2) NOT NULL,
  deductible DECIMAL(12,2) NOT NULL,
  premium DECIMAL(12,2) NOT NULL,
  valid_from TIMESTAMP NOT NULL,
  valid_to TIMESTAMP,
  is_current BOOLEAN NOT NULL
);

CREATE TABLE claim (
  id VARCHAR(10) PRIMARY KEY,
  claim_id VARCHAR(20) NOT NULL,
  claim_amount DECIMAL(12,2) NOT NULL,
  incident_date TIMESTAMP NOT NULL,
  policy_id VARCHAR(10) NOT NULL REFERENCES policy(id)
);

CREATE TABLE claim_event (
  id VARCHAR(20) PRIMARY KEY,
  claim_id VARCHAR(10) NOT NULL REFERENCES claim(id),
  event_type VARCHAR(20) NOT NULL,
  event_timestamp TIMESTAMP NOT NULL,
  event_amount DECIMAL(12,2)
);

-- Customers
INSERT INTO customer VALUES ('customer001', 'CUST001', 'Nora Copay');
INSERT INTO customer VALUES ('customer002', 'CUST002', 'Owen Deductible');
INSERT INTO customer VALUES ('customer003', 'CUST003', 'Lily Referral');

-- Policies
INSERT INTO policy VALUES ('policy001', 'P001', 'FSA', 'customer001');
INSERT INTO policy VALUES ('policy002', 'P002', 'HSA', 'customer002');
INSERT INTO policy VALUES ('policy003', 'P003', 'HRA', 'customer003');

-- Policy Coverages (SCD Type 2)
INSERT INTO policy_coverage VALUES ('p001_v1', 'policy001', 100000.00, 1000.00, 500.00, TIMESTAMP '2025-01-01 00:00:00', TIMESTAMP '2026-01-01 00:00:00', false);
INSERT INTO policy_coverage VALUES ('p001_v2', 'policy001', 150000.00, 1000.00, 650.00, TIMESTAMP '2026-01-01 00:00:00', null, true);
INSERT INTO policy_coverage VALUES ('p002_v1', 'policy002', 75000.00, 500.00, 400.00, TIMESTAMP '2025-06-01 00:00:00', TIMESTAMP '2025-12-31 23:59:59', false);
INSERT INTO policy_coverage VALUES ('p002_v2', 'policy002', 90000.00, 500.00, 450.00, TIMESTAMP '2026-02-01 00:00:00', null, true);
INSERT INTO policy_coverage VALUES ('p003_v1', 'policy003', 10000.00, 2000.00, 200.00, TIMESTAMP '2025-01-01 00:00:00', null, true);

-- Claims
INSERT INTO claim VALUES ('claim001', 'C001', 5000.00, TIMESTAMP '2025-12-15 14:30:00', 'policy001');
INSERT INTO claim VALUES ('claim002', 'C002', 1200.00, TIMESTAMP '2026-02-01 11:00:00', 'policy001');
INSERT INTO claim VALUES ('claim003', 'C003', 3000.00, TIMESTAMP '2026-01-15 16:00:00', 'policy002');
INSERT INTO claim VALUES ('claim004', 'C004', 15000.00, TIMESTAMP '2025-09-10 08:00:00', 'policy003');
INSERT INTO claim VALUES ('claim005', 'C005', 4000.00, TIMESTAMP '2025-03-01 10:00:00', 'policy001');

-- Claim Events
INSERT INTO claim_event VALUES ('c001_e1', 'claim001', 'submitted', TIMESTAMP '2025-12-20 10:00:00', 5000.00);
INSERT INTO claim_event VALUES ('c001_e2', 'claim001', 'adjusted', TIMESTAMP '2026-01-05 14:30:00', 4500.00);
INSERT INTO claim_event VALUES ('c001_e3', 'claim001', 'approved', TIMESTAMP '2026-01-10 09:00:00', 4500.00);
INSERT INTO claim_event VALUES ('c001_e4', 'claim001', 'paid', TIMESTAMP '2026-02-10 09:15:00', 4500.00);
INSERT INTO claim_event VALUES ('c002_e1', 'claim002', 'submitted', TIMESTAMP '2026-02-01 11:00:00', 1200.00);
INSERT INTO claim_event VALUES ('c003_e1', 'claim003', 'submitted', TIMESTAMP '2026-01-20 10:00:00', 3000.00);
INSERT INTO claim_event VALUES ('c003_e2', 'claim003', 'denied', TIMESTAMP '2026-01-25 14:00:00', null);
INSERT INTO claim_event VALUES ('c004_e1', 'claim004', 'submitted', TIMESTAMP '2025-09-12 09:00:00', 15000.00);
INSERT INTO claim_event VALUES ('c004_e2', 'claim004', 'denied', TIMESTAMP '2025-09-20 11:00:00', null);
INSERT INTO claim_event VALUES ('c005_e1', 'claim005', 'submitted', TIMESTAMP '2025-07-15 09:00:00', 4000.00);
INSERT INTO claim_event VALUES ('c005_e2', 'claim005', 'denied', TIMESTAMP '2025-07-20 14:00:00', null);
