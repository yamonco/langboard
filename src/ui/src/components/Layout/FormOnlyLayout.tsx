import { useTranslation } from "react-i18next";
import { forwardRef } from "react";
import CachedImage from "@/components/CachedImage";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";

interface IBaseFormOnlyLayoutProps {
    size?: "default" | "sm" | "lg";
    useLogo?: bool;
}

interface ITwoSidedFormOnlyLayoutProps extends IBaseFormOnlyLayoutProps {
    leftSide: React.ReactNode;
    rightSide: React.ReactNode;
    children?: null;
}

interface IFormOnlyLayoutProps extends IBaseFormOnlyLayoutProps {
    leftSide?: null;
    rightSide?: null;
    children: React.ReactNode;
}

export type TFormOnlyLayoutProps = IFormOnlyLayoutProps | ITwoSidedFormOnlyLayoutProps;

export const createTwoSidedSizeClassNames = (size: IBaseFormOnlyLayoutProps["size"]) => {
    let wrapperClassName;
    let widthClassName;

    switch (size) {
        case "sm":
            wrapperClassName = "flex-col xs:flex-row xs:flex-wrap xs:justify-between";
            widthClassName = "xs:w-1/2";
            break;
        case "lg":
            wrapperClassName = "flex-col md:flex-row md:flex-wrap md:justify-between";
            widthClassName = "md:w-1/2";
            break;
        default:
            wrapperClassName = "flex-col sm:flex-row sm:flex-wrap sm:justify-between";
            widthClassName = "sm:w-1/2";
            break;
    }

    return { wrapper: wrapperClassName, width: widthClassName };
};

const FormOnlyLayout = forwardRef<HTMLDivElement, TFormOnlyLayoutProps>(
    ({ size = "default", leftSide, rightSide, children, useLogo, ...props }, ref) => {
        const [t] = useTranslation();
        const isTwoSided = leftSide && rightSide;
        let content;
        let widthClassName;
        switch (size) {
            case "sm":
                widthClassName = isTwoSided ? "max-w-screen-sm" : "max-w-screen-xs";
                break;
            case "lg":
                widthClassName = isTwoSided ? "max-w-screen-lg" : "max-w-screen-md";
                break;
            default:
                widthClassName = isTwoSided ? "max-w-screen-md" : "max-w-screen-sm";
        }

        if (isTwoSided) {
            const { wrapper, width } = createTwoSidedSizeClassNames(size);
            content = (
                <Flex className={wrapper}>
                    <Box className={width}>{leftSide}</Box>
                    <Box className={width}>{rightSide}</Box>
                </Flex>
            );
        } else {
            content = children;
        }

        return (
            <Flex direction="col" items="center" justify="center" h={{ initial: "screen", xs: "auto" }} minH="screen">
                <Box w="full" className={widthClassName} ref={ref} {...props}>
                    <Flex
                        direction="col"
                        justify={{
                            initial: "between",
                            xs: "normal",
                        }}
                        h={{ initial: "full", xs: "auto" }}
                    >
                        <Box p={{ initial: "6", sm: "9" }} border={{ xs: "2" }} rounded={{ xs: "2xl" }} className="xs:border-border">
                            {useLogo && (
                                <Box mb="6">
                                    <CachedImage src="/images/logo.png" alt={t("common.Logo")} size="9" />
                                </Box>
                            )}
                            {content}
                        </Box>
                        <Box p={{ initial: "4", sm: "0" }} mt={{ sm: "2" }}>
                            <LanguageSwitcher variant="ghost" triggerType="text" />
                            <ThemeSwitcher variant="ghost" triggerType="text" />
                        </Box>
                    </Flex>
                </Box>
            </Flex>
        );
    }
);

export default FormOnlyLayout;
