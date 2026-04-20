import Phaser from "phaser";

export default class MainScene extends Phaser.Scene {
  constructor() {
    super("MainScene");
  }

  create() {
    this.add.text(20, 20, "Agentic Economy", { color: "#ffffff" });
  }
}
