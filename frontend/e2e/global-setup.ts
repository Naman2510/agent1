import { writeMicrophoneRecordings } from "./support/audio";

export default function globalSetup(): void {
  writeMicrophoneRecordings();
}
