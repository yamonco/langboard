import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import Skeleton from "@/components/base/Skeleton";

export function SkeletonBoardSettingsPage(): React.JSX.Element {
    return (
        <Flex direction="col" gap="3" p={{ initial: "4", md: "6", lg: "8" }} items="center">
            <Box w="full" className="max-w-screen-sm">
                <Skeleton h="8" mb="2" className="scroll-m-20" />
                <Box items="center" justify="center" py="4" gap="2" w="full" wrap display={{ initial: "hidden", sm: "flex" }}>
                    <Skeleton h="6" className="w-1/5" />
                    <Skeleton h="6" className="w-1/5" />
                    <Skeleton h="6" className="w-1/5" />
                    <Skeleton h="6" className="w-1/5" />
                </Box>
            </Box>
        </Flex>
    );
}
