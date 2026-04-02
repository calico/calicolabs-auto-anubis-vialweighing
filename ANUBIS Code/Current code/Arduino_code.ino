// Define the pins for the two reed sensors
const int reedPin1 = 5;
const int reedPin2 = 7;

void setup() {
  Serial.begin(115200);
  
  // Set up both pins as inputs with internal pull-up resistors
  pinMode(reedPin1, INPUT_PULLUP);
  pinMode(reedPin2, INPUT_PULLUP);
}

void loop() {
  // Only send data when the Python script requests it
  if (Serial.available() > 0) {
    char incomingByte = Serial.read();
    
    // Check if the incoming byte is the request character '?'
    if (incomingByte == '?') {
      // Read the state of both sensors
      int state1 = digitalRead(reedPin1);
      int state2 = digitalRead(reedPin2);

      // Determine the status string for the first sensor (LOW = Open)
      String status1 = (state1 == LOW) ? "Open" : "Closed";
      
      // Determine the status string for the second sensor (LOW = Open)
      String status2 = (state2 == LOW) ? "Open" : "Closed";

      // Send the combined status string with the correct pin numbers
      // Format: "pin5:State,pin7:State"
      Serial.print("pin5:");
      Serial.print(status1);
      Serial.print(",");
      Serial.print("pin7:");
      Serial.println(status2);
    }
  }
}