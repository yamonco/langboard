export function createSubmitGuard() {
    let isSubmitting = false;

    return {
        tryStart(): boolean {
            if (isSubmitting) {
                return false;
            }

            isSubmitting = true;
            return true;
        },
        finish() {
            isSubmitting = false;
        },
    };
}
