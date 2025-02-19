import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
	Card,
	CardContent,
	CardDescription,
	CardFooter,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";

export const LoginForm = () => {
	return (
		<Card className="w-full max-w-lg">
			<CardHeader>
				<CardTitle>Login In</CardTitle>
				<CardDescription>
					Please enter your credentials to login
				</CardDescription>
			</CardHeader>
			<CardContent>
				<form>
					<div className="grid w-full items-center gap-4">
						<div className="flex flex-col space-y-1.5">
							<Label htmlFor="username">Username</Label>
							<Input id="name" placeholder="Enter username" />
						</div>
						<div className="flex flex-col space-y-1.5">
							<Label htmlFor="password">Password</Label>
							<Input
								id="password"
								type="password"
								placeholder="Enter password"
							/>
						</div>
					</div>
				</form>
			</CardContent>
			<CardFooter className="flex justify-end">
				<Button type="submit">Login</Button>
			</CardFooter>
		</Card>
	);
};
