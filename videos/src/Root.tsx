import { Composition } from "remotion";
import { TradingBotIntro } from "./compositions/TradingBotIntro";
import { TradingBotPromo } from "./compositions/TradingBotPromo";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="TradingBotPromo"
        component={TradingBotPromo}
        durationInFrames={900}
        fps={30}
        width={1920}
        height={1080}
      />
      <Composition
        id="TradingBotIntro"
        component={TradingBotIntro}
        durationInFrames={300}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
