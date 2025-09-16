-- Clear old data
DELETE FROM activities;

-- Insert sample activities for Aryan Patel (user_id = 1)
INSERT INTO activities (user_id, date, travel_mode, travel_km, electricity_kwh, diet_type, co2_kg)
VALUES 
(1, "2025-08-20", "Car", 10, 0, "Non-Veg", 2.5),
(1, "2025-08-21", "Bus", 15, 0, "Veg", 1.2),
(1, "2025-08-22", "Bike", 5, 0, "Veg", 0.8),
(1, "2025-08-23", "Train", 50, 0, "Veg", 3.0),
(1, "2025-08-24", "Walk", 2, 0, "Veg", 0.1),
(1, "2025-08-25", "Car", 8, 0, "Non-Veg", 2.0),
(1, "2025-08-26", "Bus", 12, 0, "Veg", 1.0),
(1, "2025-08-27", "Car", 20, 0, "Veg", 3.5),
(1, "2025-08-28", "Bike", 6, 0, "Veg", 0.9),
(1, "2025-08-29", "Walk", 3, 0, "Veg", 0.1),
(1, "2025-08-30", "Car", 15, 0, "Non-Veg", 2.8),
(1, "2025-08-30", "Electricity", 0, 12, "Veg", 4.5);
