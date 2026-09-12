// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @notice Checks-effects-interactions. Same invariant, same assertion.
contract SafeVault {
    mapping(address => uint256) public balances;
    uint256 public totalDeposits;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
        totalDeposits += msg.value;
    }

    function withdraw() external {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "nothing to withdraw");

        balances[msg.sender] = 0;
        totalDeposits -= amount;

        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");

        /// @dev Solvency invariant: the vault never owes more than it holds.
        assert(totalDeposits <= address(this).balance);
    }
}
