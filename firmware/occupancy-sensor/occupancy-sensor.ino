void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 5000) delay(10);
  
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.println("LED blinking - board is alive");
  Serial.println("Touch a wire from 3V3 to GND briefly and tell me if you see a spark or feel warmth");
}

void loop() {
  digitalWrite(LED_BUILTIN, LOW);  // LOW = ON for XIAO
  Serial.println("LED ON");
  delay(500);
  digitalWrite(LED_BUILTIN, HIGH);
  Serial.println("LED OFF");
  delay(500);
}