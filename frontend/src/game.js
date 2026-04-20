import Phaser from "phaser";
import MainScene from "./scenes/MainScene";

new Phaser.Game({
  type: Phaser.AUTO,
  width: 960,
  height: 540,
  scene: [MainScene],
  parent: "app",
});
